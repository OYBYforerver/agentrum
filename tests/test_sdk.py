"""Consumer SDK: ref parsing, resolve + cache fallback, prompt rendering,
skill extraction (with traversal-safe extraction)."""

import io
import tarfile

import httpx
import pytest

from agentrum.sdk import Registry, Resolved, parse_ref


def _resource_body(kind="MCPServer", spec=None):
    return {
        "kind": kind,
        "namespace": "payment",
        "name": "gateway",
        "visibility": "internal",
        "catalog": {"description": "payment mcp"},
        "latest_version": {"tag": "v2", "spec": spec or {}},
    }


MCP_SPEC = {
    "transport": "streamable-http",
    "endpoint": "https://pay.internal/mcp",
    "headers": [
        {"name": "X-Api-Key", "value": "literal-key"},
        {"name": "X-Secret", "valueFrom": {"secretRef": {"name": "s", "key": "k"}}},
    ],
}


def _registry(tmp_path, handler) -> Registry:
    return Registry(
        "https://registry.internal",
        ak="ark-ak-x",
        sk="ark-sk-y",
        cache_dir=tmp_path / "cache",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_parse_ref():
    assert parse_ref("MCPServer/payment/gateway") == ("MCPServer", "payment", "gateway")
    assert parse_ref("mcpserver/payment/gateway") == ("MCPServer", "payment", "gateway")
    with pytest.raises(ValueError):
        parse_ref("MCPServer/gateway")
    with pytest.raises(ValueError):
        parse_ref("Workflow/a/b")


def test_resolve_mcp_server(tmp_path):
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        return httpx.Response(200, json=_resource_body(spec=MCP_SPEC))

    reg = _registry(tmp_path, handler)
    resolved = reg.resolve("MCPServer/payment/gateway")
    assert resolved.endpoint == "https://pay.internal/mcp"
    assert resolved.transport == "streamable-http"
    # literal headers only — secretRef-backed values never leave the registry
    assert resolved.headers == {"X-Api-Key": "literal-key"}
    assert resolved.tag == "v2"
    assert seen_auth and seen_auth[0].startswith("Basic ")


def test_resolve_falls_back_to_stale_cache_when_unreachable(tmp_path):
    state = {"up": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["up"]:
            return httpx.Response(200, json=_resource_body(spec=MCP_SPEC))
        raise httpx.ConnectError("boom")

    reg = _registry(tmp_path, handler)
    fresh = reg.resolve("MCPServer/payment/gateway")
    assert not fresh.stale

    state["up"] = False
    stale = reg.resolve("MCPServer/payment/gateway")
    assert stale.stale
    assert stale.endpoint == fresh.endpoint


def test_resolve_4xx_is_authoritative_no_cache_fallback(tmp_path):
    state = {"ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["ok"]:
            return httpx.Response(200, json=_resource_body(spec=MCP_SPEC))
        return httpx.Response(404, json={"detail": "not found"})

    reg = _registry(tmp_path, handler)
    reg.resolve("MCPServer/payment/gateway")
    state["ok"] = False
    with pytest.raises(httpx.HTTPStatusError):
        reg.resolve("MCPServer/payment/gateway")


def test_prompt_render_contract():
    spec = {
        "template": "Review this {{ language }} code strictly.\n{{ style }}",
        "variables": [
            {"name": "language", "required": True},
            {"name": "style", "required": False, "description": "tone"},
        ],
    }
    prompt = Resolved(kind="Prompt", namespace="t", name="p", spec=spec)
    out = prompt.render(language="python", style="be blunt")
    assert "Review this python code strictly." in out
    assert "be blunt" in out

    with pytest.raises(ValueError, match="required"):
        prompt.render(style="x")
    with pytest.raises(ValueError, match="undeclared"):
        prompt.render(language="python", extra="nope")


def test_fetch_skill_extracts_pinned_tree(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        skill = tarfile.TarInfo("SKILL.md")
        data = b"# pinned skill\n"
        skill.size = len(data)
        tar.addfile(skill, io.BytesIO(data))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/content")
        return httpx.Response(
            200,
            content=buf.getvalue(),
            headers={"X-Agentrum-Sha": "a" * 40},
        )

    reg = _registry(tmp_path, handler)
    dest = reg.fetch_skill("Skill/payment/gateway", dest=tmp_path / "skills")
    assert (dest / "SKILL.md").read_text() == "# pinned skill\n"


def test_fetch_skill_refuses_path_traversal(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        evil = tarfile.TarInfo("../../evil.txt")
        data = b"pwn"
        evil.size = len(data)
        tar.addfile(evil, io.BytesIO(data))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=buf.getvalue())

    reg = _registry(tmp_path, handler)
    with pytest.raises(Exception):  # noqa: B017 - tarfile's filter error type
        reg.fetch_skill("Skill/payment/gateway", dest=tmp_path / "skills")
    assert not (tmp_path / "evil.txt").exists()
