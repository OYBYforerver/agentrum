"""Per-kind spec validation. Specs are stored loosely (extras allowed) but
must satisfy the minimal contract of their kind — a registry is only
trustworthy if its entries are well-formed."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, model_validator

from agentrum import errors

# DNS-1123 label: what a Kubernetes namespace name must look like.
_CLUSTER_NAMESPACE_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
# Namespaces a workload registry has no business creating workloads in.
_RESERVED_CLUSTER_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
# Container image reference (repo[:port]/path[:tag][@digest]) — permissive but
# rejects schemes ("https://...") and whitespace, which are never valid.
_IMAGE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(:[0-9]+)?(/[A-Za-z0-9._/-]+)?"
    r"(:[A-Za-z0-9._-]+)?(@[A-Za-z0-9+.-]+(:[A-Fa-f0-9]+)?)?$"
)
# {{variable}} placeholders in Prompt templates (whitespace-tolerant).
_TEMPLATE_PLACEHOLDERS_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


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
    """Container image plus the protocol metadata a catalog consumer needs.

    `env` describes what the process needs regardless of where it runs;
    cluster placement (namespace/replicas) belongs to the Deployment spec."""

    image: str
    env: list[EnvVar] = []
    # Catalog/interop metadata (all optional — the image is the contract).
    framework: str | None = None  # langgraph / crewai / adk / ...
    protocol: Literal["mcp", "a2a", "openapi", "http", "custom"] | None = None
    # A2A agent card (/.well-known/agent.json) when the agent speaks A2A.
    agent_card_url: HttpUrl | None = None
    capabilities: list[str] = []

    @model_validator(mode="after")
    def _sane_image(self) -> "AgentSpec":
        if "://" in self.image or any(c.isspace() for c in self.image) or not _IMAGE_RE.match(self.image):
            raise ValueError(
                f"image {self.image!r} is not a valid container image reference"
            )
        return self

    @model_validator(mode="after")
    def _a2a_needs_card(self) -> "AgentSpec":
        if self.protocol == "a2a" and not self.agent_card_url:
            raise ValueError("protocol 'a2a' requires agent_card_url")
        return self


class MCPServerSpec(BaseSpec):
    transport: Literal["streamable-http", "sse", "stdio"]
    endpoint: HttpUrl | None = None
    command: str | None = None
    args: list[str] = []  # stdio launch arguments (npx -y ..., python -m ...)
    env: list[EnvVar] = []
    # Remote auth/routing headers. Literal values are published to consumers
    # in connection snippets; value_from.secret_ref entries stay secret (they
    # are resolved server-side for health probes only).
    headers: list[EnvVar] = []

    @model_validator(mode="after")
    def _check_transport_target(self) -> "MCPServerSpec":
        if self.transport in ("streamable-http", "sse") and not self.endpoint:
            raise ValueError(f"endpoint is required for transport {self.transport!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for transport 'stdio'")
        if self.transport != "stdio" and self.args:
            raise ValueError("args are only valid for transport 'stdio'")
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
        declared = set(names)
        used = set(_TEMPLATE_PLACEHOLDERS_RE.findall(self.template))
        undeclared = sorted(used - declared)
        unused = sorted(declared - used)
        if undeclared:
            raise ValueError(
                f"template uses {undeclared} but they are not declared in variables"
            )
        if unused:
            raise ValueError(
                f"variables {unused} are declared but never used in the template"
            )
        return self


class DeploymentSpec(BaseSpec):
    """Desired state for running a published resource on a runtime."""

    target_kind: Literal["Agent", "MCPServer"]
    target_namespace: str
    target_name: str
    tag: str | None = Field(default=None, max_length=63)  # pin a version tag; default = latest
    cluster_namespace: str = "default"
    replicas: int = Field(default=1, ge=1, le=50)
    runtime: Literal["kubernetes"] = "kubernetes"
    image_pull_policy: Literal["IfNotPresent", "Always", "Never"] = "IfNotPresent"
    port: int = Field(default=8000, ge=1, le=65535)

    @model_validator(mode="after")
    def _sane_cluster_namespace(self) -> "DeploymentSpec":
        if not _CLUSTER_NAMESPACE_RE.match(self.cluster_namespace):
            raise ValueError(
                "cluster_namespace must be a DNS-1123 label (lowercase alphanumeric/'-', 1-63 chars)"
            )
        if self.cluster_namespace in _RESERVED_CLUSTER_NAMESPACES:
            raise ValueError(
                f"cluster_namespace {self.cluster_namespace!r} is a reserved Kubernetes namespace"
            )
        return self


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


# Bump when a spec shape changes meaningfully. Stored inside every published
# version so consumers (and future migrations) can tell shapes apart; specs
# published before this field existed are implicitly version 1.
SPEC_VERSION = 1


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
    dump = parsed.model_dump(mode="json")
    dump["spec_version"] = SPEC_VERSION
    return dump


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
