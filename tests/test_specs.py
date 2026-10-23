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
