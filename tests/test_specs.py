import pytest

from agentrum import errors
from agentrum.schemas.specs import validate_spec


def test_agent_requires_image():
    with pytest.raises(errors.ValidationError):
        validate_spec("Agent", {"framework": "langgraph"})
    ok = validate_spec("Agent", {"image": "reg.local/a:1", "framework": "langgraph"})
    assert ok["image"] == "reg.local/a:1"
    assert ok["framework"] == "langgraph"  # extras are preserved


def test_mcpserver_transport_contract():
    with pytest.raises(errors.ValidationError):
        validate_spec("MCPServer", {"transport": "streamable-http"})  # endpoint missing
    with pytest.raises(errors.ValidationError):
        validate_spec("MCPServer", {"transport": "stdio"})  # command missing
    ok = validate_spec("MCPServer", {"transport": "stdio", "command": "npx -y x"})
    assert ok["transport"] == "stdio"


def test_prompt_requires_template_and_unknown_kind():
    with pytest.raises(errors.ValidationError):
        validate_spec("Prompt", {"notes": "no template"})
    with pytest.raises(errors.ValidationError):
        validate_spec("Workflow", {})  # unregistered kind


def test_spec_must_be_object():
    with pytest.raises(errors.ValidationError):
        validate_spec("Skill", "just-a-string")


def test_skill_git_source_contract():
    # both modes at once → rejected
    with pytest.raises(errors.ValidationError):
        validate_spec("Skill", {"source": {"git": {"url": "https://x/r.git"}}, "instructions": "y"})
    # neither → rejected
    with pytest.raises(errors.ValidationError):
        validate_spec("Skill", {})
    # git mode passes through with ref
    ok = validate_spec("Skill", {"source": {"git": {"url": "https://x/r.git", "ref": "v1"}}})
    assert ok["source"]["git"]["ref"] == "v1"
    # inline mode still works
    assert validate_spec("Skill", {"instructions": "do"})["instructions"] == "do"


def test_agent_endpoint_and_protocol_contracts():
    # Externally-hosted agents can declare where consumers reach them.
    spec = validate_spec(
        "Agent",
        {"image": "ghcr.io/acme/agent:v1", "endpoint": "https://agents.acme.internal/pay"},
    )
    assert spec["endpoint"] == "https://agents.acme.internal/pay"

    # openapi agents must point at their contract document, like a2a needs
    # its agent card.
    with pytest.raises(errors.ValidationError):
        validate_spec("Agent", {"image": "i:v1", "protocol": "openapi"})
    spec = validate_spec(
        "Agent",
        {"image": "i:v1", "protocol": "openapi", "openapi_url": "https://x/openapi.json"},
    )
    assert spec["openapi_url"] == "https://x/openapi.json"
