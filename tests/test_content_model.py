"""Unit tests for the content-model adaptations: spec validation for the
ecosystem fields, prompt placeholder consistency, spec_version stamping,
connection snippets and skill frontmatter parsing."""

import asyncio

import pytest

from agentrum import errors
from agentrum.schemas.specs import SPEC_VERSION, validate_spec
from agentrum.services.connect_service import build
from agentrum.services.git_service import parse_frontmatter


def _resource(kind="MCPServer", namespace="team-a", name="gw"):
    from agentrum.db import models

    return models.Resource(
        kind=kind, namespace=namespace, name=name, visibility="internal",
        created_by=__import__("uuid").uuid4(),
    )


# --- spec validation ----------------------------------------------------------

def test_mcp_stdio_accepts_args():
    spec = validate_spec("MCPServer", {
        "transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-weather"],
    })
    assert spec["args"] == ["-y", "@modelcontextprotocol/server-weather"]
    assert spec["spec_version"] == SPEC_VERSION


def test_mcp_args_rejected_for_remote_transport():
    with pytest.raises(errors.ValidationError):
        validate_spec("MCPServer", {
            "transport": "streamable-http", "endpoint": "https://x/mcp", "args": ["-y"],
        })


def test_mcp_headers_accepted():
    spec = validate_spec("MCPServer", {
        "transport": "streamable-http", "endpoint": "https://x/mcp",
        "headers": [{"name": "Authorization", "value": "Bearer t"}],
    })
    assert spec["headers"][0]["name"] == "Authorization"


def test_agent_a2a_requires_agent_card():
    with pytest.raises(errors.ValidationError):
        validate_spec("Agent", {"image": "reg/a:1", "protocol": "a2a"})


def test_agent_metadata_fields():
    spec = validate_spec("Agent", {
        "image": "reg/a:1", "framework": "langgraph", "protocol": "a2a",
        "agent_card_url": "https://agent.example/.well-known/agent.json",
        "capabilities": ["code", "search"],
    })
    assert spec["framework"] == "langgraph"
    assert spec["capabilities"] == ["code", "search"]
    assert spec["spec_version"] == SPEC_VERSION


def test_prompt_placeholders_must_match_variables():
    with pytest.raises(errors.ValidationError, match="not declared"):
        validate_spec("Prompt", {"template": "hi {{name}}"})
    with pytest.raises(errors.ValidationError, match="never used"):
        validate_spec("Prompt", {
            "template": "hi", "variables": [{"name": "name"}],
        })
    ok = validate_spec("Prompt", {
        "template": "hi {{ name }}", "variables": [{"name": "name"}],
    })
    assert ok["variables"][0]["name"] == "name"


def test_every_spec_is_stamped_with_spec_version():
    for kind, sample in (
        ("Agent", {"image": "reg/a:1"}),
        ("MCPServer", {"transport": "stdio", "command": "uvx"}),
        ("Prompt", {"template": "t"}),
        ("Skill", {"instructions": "do"}),
        ("Deployment", {"target_kind": "Agent", "target_namespace": "ns", "target_name": "a"}),
    ):
        assert validate_spec(kind, sample)["spec_version"] == SPEC_VERSION, kind


# --- connection snippets ------------------------------------------------------

def test_connect_stdio_snippet():
    out = build(_resource(name="weather"), {
        "transport": "stdio", "command": "npx", "args": ["-y", "@mcp/weather"],
        "env": [{"name": "API_KEY", "value_from": {"secret_ref": {"name": "creds", "key": "k"}}}],
    })
    assert out["stdio"]["command"] == "npx"
    assert "claude mcp add weather -- npx -y @mcp/weather" in out["clients"]["claude_code"]
    assert any("API_KEY" in n for n in out["notes"])  # secret env flagged, not leaked


def test_connect_remote_snippet_with_headers():
    out = build(_resource(name="remote"), {
        "transport": "streamable-http", "endpoint": "https://mcp.internal/x",
        "headers": [{"name": "X-Team", "value": "acme"}],
    })
    assert out["remote"]["url"] == "https://mcp.internal/x"
    assert out["clients"]["cursor"]["mcpServers"]["remote"]["headers"] == {"X-Team": "acme"}
    assert "--header" in out["clients"]["claude_code"]


def test_connect_rejects_non_mcp():
    with pytest.raises(errors.ValidationError):
        build(_resource(kind="Agent"), {"image": "reg/a:1"})


# --- skill frontmatter --------------------------------------------------------

def test_parse_frontmatter_extracts_yaml_block():
    meta, body = parse_frontmatter("---\nname: demo\ndescription: A demo skill\n---\n# body\n")
    assert meta == {"name": "demo", "description": "A demo skill"}
    assert body.startswith("# body")


def test_parse_frontmatter_absent():
    meta, body = parse_frontmatter("# just markdown\n")
    assert meta == {}
    assert body.startswith("# just")


def test_parse_frontmatter_invalid_yaml():
    with pytest.raises(errors.ValidationError):
        parse_frontmatter("---\n: : : [broken\n---\nbody")


# --- MCP probe handshake ------------------------------------------------------

def test_probe_initialize_parses_json_response():
    import asyncio

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"].startswith("application/json")
        assert request.headers["X-Team"] == "acme"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "serverInfo": {"name": "weather", "version": "1.2.0"}}})

    transport = httpx.MockTransport(handler)

    async def run():
        async with httpx.AsyncClient(transport=transport) as http:
            from agentrum.services.probe_service import _probe_streamable_http as probe
            return await probe(http, "https://mcp/x", {"X-Team": "acme"})
    cond = asyncio.run(run())
    assert cond["status"] == "True"
    assert "weather v1.2.0" in cond["message"]


def test_probe_initialize_sse_framed_response():
    import httpx

    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"sse"}}}\n\n'
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        from agentrum.services.probe_service import _probe_streamable_http

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await _probe_streamable_http(http, "https://mcp/x", {})
    cond = asyncio.run(run())
    assert cond is not None and cond["status"] == "True"
    assert "sse" in cond["message"]


def test_probe_initialize_failure_falls_back():
    import httpx

    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        from agentrum.services.probe_service import _probe_streamable_http

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await _probe_streamable_http(http, "https://mcp/x", {})
    assert asyncio.run(run()) is None  # None → caller falls back to the GET heuristic
