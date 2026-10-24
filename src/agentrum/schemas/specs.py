"""Per-kind spec validation. Specs are stored loosely (extras allowed) but
must satisfy the minimal contract of their kind — a registry is only
trustworthy if its entries are well-formed."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, model_validator

from agentrum import errors


class BaseSpec(BaseModel):
    model_config = ConfigDict(extra="allow")


class SecretRef(BaseModel):
    """Reference to a Secret resource: {name, key, namespace?}."""

    name: str
    key: str
    namespace: str | None = None


class EnvFrom(BaseModel):
    secret_ref: SecretRef


class EnvVar(BaseSpec):
    name: str
    value: str | None = None
    value_from: EnvFrom | None = None

    @model_validator(mode="after")
    def _either_value_or_ref(self) -> "EnvVar":
        if (self.value is None) == (self.value_from is None):
            raise ValueError("env var needs exactly one of 'value' or 'value_from'")
        return self


class AgentSpec(BaseSpec):
    image: str
    env: list[EnvVar] = []


class MCPServerSpec(BaseSpec):
    transport: Literal["streamable-http", "sse", "stdio"]
    endpoint: HttpUrl | None = None
    command: str | None = None
    env: list[EnvVar] = []

    @model_validator(mode="after")
    def _check_transport_target(self) -> "MCPServerSpec":
        if self.transport in ("streamable-http", "sse") and not self.endpoint:
            raise ValueError(f"endpoint is required for transport {self.transport!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for transport 'stdio'")
        return self


class GitSource(BaseModel):
    """Git-backed skill content. The ref is resolved to a commit SHA at
    publish time and the SHA is locked into the immutable version."""

    url: str
    ref: str = "HEAD"
    subdirectory: str | None = None
    credentials_ref: str | None = None  # Secret resource holding username/password


class SkillSource(BaseModel):
    git: GitSource


class SkillSpec(BaseSpec):
    entrypoint: str | None = None
    instructions: str | None = None
    source: SkillSource | None = None

    @model_validator(mode="after")
    def _one_source_mode(self) -> "SkillSpec":
        has_git = self.source is not None and bool(self.source.git.url)
        has_content = bool(self.instructions)
        if has_git and has_content:
            raise ValueError("use either source.git or inline instructions, not both")
        if not has_git and not has_content:
            raise ValueError("a skill needs source.git or inline instructions")
        return self


class PromptVariable(BaseModel):
    """Declared template variable: powers structured forms and MCP callers."""

    name: str
    required: bool = False
    description: str | None = None


class PromptSpec(BaseSpec):
    template: str
    variables: list[PromptVariable] = []

    @model_validator(mode="after")
    def _unique_names(self) -> "PromptSpec":
        names = [v.name for v in self.variables]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate variable names: {sorted(dupes)}")
        return self


class DeploymentSpec(BaseSpec):
    """Desired state for running a published resource on a runtime."""

    target_kind: Literal["Agent", "MCPServer"]
    target_namespace: str
    target_name: str
    tag: str | None = None  # pin a version tag; default = latest
    cluster_namespace: str = "default"
    replicas: int = 1
    runtime: Literal["kubernetes"] = "kubernetes"
    image_pull_policy: Literal["IfNotPresent", "Always", "Never"] = "IfNotPresent"
    port: int = 8000


class CatalogInfo(BaseModel):
    """Mutable catalog metadata. Field names follow package-registry
    conventions (npm/PyPI); MCPServer entries additionally align with the
    MCP Registry server.json shape."""

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    long_description: str | None = None
    icon: HttpUrl | None = None
    keywords: list[str] = []
    authors: list[str] = []
    license: str | None = None
    links: dict[str, HttpUrl] = {}


SPEC_MODELS: dict[str, type[BaseSpec]] = {
    "Agent": AgentSpec,
    "MCPServer": MCPServerSpec,
    "Skill": SkillSpec,
    "Prompt": PromptSpec,
    "Deployment": DeploymentSpec,
}


def validate_spec(kind: str, spec: Any) -> dict:
    """Validate `spec` against its kind. Returns the normalized dict for
    storage; raises ValidationError (domain) on failure.

    Secrets are handled by the secrets service (their payload is encrypted,
    not stored as spec)."""
    if kind == "Secret":
        raise errors.ValidationError("Secret resources use the /v1/secrets API")
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


def validate_catalog(catalog: Any) -> dict:
    if catalog is None:
        return {}
    if not isinstance(catalog, dict):
        raise errors.ValidationError("catalog must be a JSON object")
    try:
        return CatalogInfo.model_validate(catalog).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", []))
        raise errors.ValidationError(f"invalid catalog at '{loc}': {first['msg']}") from exc
