"""Per-kind spec validation. Specs are stored loosely (extras allowed) but
must satisfy the minimal contract of their kind — a registry is only
trustworthy if its entries are well-formed."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, model_validator

from agentrum import errors


class BaseSpec(BaseModel):
    model_config = ConfigDict(extra="allow")


class AgentSpec(BaseSpec):
    image: str


class MCPServerSpec(BaseSpec):
    transport: Literal["streamable-http", "sse", "stdio"]
    endpoint: HttpUrl | None = None
    command: str | None = None

    @model_validator(mode="after")
    def _check_transport_target(self) -> "MCPServerSpec":
        if self.transport in ("streamable-http", "sse") and not self.endpoint:
            raise ValueError(f"endpoint is required for transport {self.transport!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for transport 'stdio'")
        return self


class SkillSpec(BaseSpec):
    entrypoint: str | None = None
    instructions: str | None = None


class PromptSpec(BaseSpec):
    template: str


SPEC_MODELS: dict[str, type[BaseSpec]] = {
    "Agent": AgentSpec,
    "MCPServer": MCPServerSpec,
    "Skill": SkillSpec,
    "Prompt": PromptSpec,
}


def validate_spec(kind: str, spec: Any) -> dict:
    """Validate `spec` against its kind. Returns the normalized dict for
    storage; raises ValidationError (domain) on failure."""
    model = SPEC_MODELS.get(kind)
    if model is None:
        raise errors.ValidationError(f"no spec schema registered for kind {kind!r}")
    if not isinstance(spec, dict):
        raise errors.ValidationError(f"{kind} spec must be a JSON object")
    try:
        parsed = model.model_validate(spec)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", []))
        raise errors.ValidationError(f"invalid {kind} spec at '{loc}': {first['msg']}") from exc
    return parsed.model_dump(mode="json")
