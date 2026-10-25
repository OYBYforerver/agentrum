"""Consumer SDK: resolve registry entries into usable connection info.

For applications that consume registry assets at runtime::

    import agentrum.sdk as agentrum

    registry = agentrum.Registry("https://registry.internal", ak=..., sk=...)
    server = registry.resolve("MCPServer/payment/payment-gateway")

    # MCP servers: connect with any MCP client
    async with streamablehttp_client(server.endpoint, headers=server.headers) as ...:
        ...

    # Skills: fetch the pinned tree (works for private repos — the registry
    # holds the credentials and streams the bytes)
    registry.fetch_skill("Skill/team/pay-skill", dest="./skills")

    # Prompts: template + declared variables, rendered locally
    prompt = registry.resolve("Prompt/team/review-style")
    text = prompt.render(language="python")

Resolution results are cached on disk (TTL, then stale-if-error): a registry
outage must never take the consuming application down — that is the whole
point of a control-plane registry.

Credentials resolution order: explicit arguments, then AGENTRUM_AK/AGENTRUM_SK
(or AGENTRUM_TOKEN) environment variables, then the file written by
`agentrum login` (~/.agentrum/credentials.json).
"""

from __future__ import annotations

import io
import json
import os
import re
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self
from urllib.parse import quote

import httpx

_KINDS = {"agent": "Agent", "mcpserver": "MCPServer", "skill": "Skill", "prompt": "Prompt"}
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_CREDENTIALS = Path.home() / ".agentrum" / "credentials.json"


def parse_ref(ref: str) -> tuple[str, str, str]:
    """'MCPServer/payment/payment-gateway' → ('MCPServer', 'payment',
    'payment-gateway'). Kind matching is case-insensitive."""
    parts = [p for p in ref.strip().split("/") if p]
    if len(parts) != 3:
        raise ValueError(f"expected Kind/namespace/name, got {ref!r}")
    kind = _KINDS.get(parts[0].lower())
    if kind is None:
        raise ValueError(f"unknown kind {parts[0]!r} (use Agent/MCPServer/Skill/Prompt)")
    return kind, parts[1], parts[2]


@dataclass
class Resolved:
    """One registry entry at a concrete version, ready to consume."""

    kind: str
    namespace: str
    name: str
    spec: dict
    tag: str | None = None
    catalog: dict = field(default_factory=dict)
    stale: bool = False  # served from cache after the registry became unreachable

    # --- MCPServer / Agent ---------------------------------------------------
    @property
    def endpoint(self) -> str | None:
        return self.spec.get("endpoint")

    @property
    def transport(self) -> str | None:
        return self.spec.get("transport")

    @property
    def headers(self) -> dict[str, str]:
        """Literal connection headers. secretRef-backed header values never
        leave the registry; arrange those out-of-band with the owner."""
        return {
            h["name"]: h["value"] for h in self.spec.get("headers") or [] if h.get("value")
        }

    # --- Skill ----------------------------------------------------------------
    @property
    def sha(self) -> str | None:
        return ((self.spec.get("source") or {}).get("git") or {}).get("resolved_sha")

    @property
    def instructions(self) -> str | None:
        return self.spec.get("instructions")

    # --- Prompt ---------------------------------------------------------------
    def render(self, **variables: object) -> str:
        """Fill the declared template variables. Missing required variables
        (and unknown ones) are errors — prompt contracts are explicit."""
        from agentrum.services import prompt_service

        try:
            return prompt_service.render(self.spec, dict(variables))
        except Exception as exc:  # keep the SDK's ValueError contract
            raise ValueError(str(exc)) from exc


class Registry:
    """Registry client with a disk cache. `resolve()` prefers fresh data,
    falls back to the cached copy (marked stale) when the registry is
    unreachable."""

    def __init__(
        self,
        server: str | None = None,
        *,
        ak: str | None = None,
        sk: str | None = None,
        token: str | None = None,
        cache_dir: str | Path | None = None,
        ttl_seconds: float = 300,
        timeout: float = 10,
        http_client: httpx.Client | None = None,
    ) -> None:
        stored = self._stored_credentials()
        self.server = (server or os.environ.get("AGENTRUM_SERVER") or stored.get("server") or "").rstrip("/")
        if not self.server:
            raise ValueError("no registry server given (argument, AGENTRUM_SERVER, or `agentrum login`)")
        self.ak = ak or os.environ.get("AGENTRUM_AK") or stored.get("ak")
        self.sk = sk or os.environ.get("AGENTRUM_SK") or stored.get("sk")
        self.token = token or os.environ.get("AGENTRUM_TOKEN") or stored.get("token")
        if not ((self.ak and self.sk) or self.token):
            raise ValueError(
                "no credentials (ak/sk arguments, AGENTRUM_AK/AGENTRUM_SK, or `agentrum login`)"
            )
        self.cache_dir = Path(cache_dir) if cache_dir else Path(
            os.environ.get("AGENTRUM_CACHE_DIR", Path.home() / ".agentrum" / "cache")
        )
        self.ttl = ttl_seconds
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout)

    @staticmethod
    def _stored_credentials() -> dict:
        try:
            return json.loads(_CREDENTIALS.read_text())
        except (OSError, ValueError):
            return {}

    def _auth_kwargs(self) -> dict:
        if self.ak and self.sk:
            return {"auth": (self.ak, self.sk)}
        return {"headers": {"Authorization": f"Bearer {self.token}"}}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _cache_path(self, ref: str, tag: str | None) -> Path:
        import hashlib

        key = hashlib.sha256(f"{self.server}|{ref}|{tag or ''}".encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.json"

    def _cached(self, ref: str, tag: str | None) -> tuple[dict | None, float]:
        path = self._cache_path(ref, tag)
        try:
            blob = json.loads(path.read_text())
            return blob.get("body"), blob.get("ts", 0.0)
        except (OSError, ValueError):
            return None, 0.0

    def _store(self, ref: str, tag: str | None, body: dict) -> None:
        path = self._cache_path(ref, tag)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": time.time(), "body": body}))
            os.replace(tmp, path)
        except OSError:
            pass  # cache is best-effort

    def resolve(self, ref: str, *, tag: str | None = None) -> Resolved:
        kind, namespace, name = parse_ref(ref)
        path = f"/v1/resources/{quote(kind)}/{quote(namespace)}/{quote(name)}"
        params = {"tag": tag} if tag else None

        cache_key = f"{kind}/{namespace}/{name}"
        try:
            resp = self._client.get(f"{self.server}{path}", params=params, **self._auth_kwargs())
            resp.raise_for_status()
            body = resp.json()
            self._store(cache_key, tag, body)
            stale = False
        except httpx.HTTPStatusError as exc:
            # 4xx means the answer is authoritative (bad credentials, no
            # such resource) — serving cache would hide real problems.
            if exc.response.status_code < 500:
                raise
            body, _ = self._cached(cache_key, tag)
            if body is None:
                raise
            stale = True
        except httpx.HTTPError:
            # Unreachable registry: stale cache beats an outage.
            body, _ = self._cached(cache_key, tag)
            if body is None:
                raise
            stale = True

        rv = body.get("latest_version") or {}
        spec = rv.get("spec") or {}
        return Resolved(
            kind=kind,
            namespace=namespace,
            name=name,
            spec=spec,
            tag=tag or rv.get("tag"),
            catalog=body.get("catalog") or {},
            stale=stale,
        )

    def fetch_skill(self, ref: str, *, dest: str | Path, tag: str | None = None) -> Path:
        """Download the skill's pinned tree and extract it into `dest`.
        Returns the destination directory. Extraction uses tarfile's `data`
        filter — member paths outside `dest` are refused."""
        kind, namespace, name = parse_ref(ref)
        if kind != "Skill":
            raise ValueError("fetch_skill() is for Skill resources")
        path = (
            f"/v1/resources/Skill/{quote(namespace)}/{quote(name)}/content"
        )
        resp = self._client.get(
            f"{self.server}{path}", params={"tag": tag} if tag else None, **self._auth_kwargs()
        )
        resp.raise_for_status()
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            tar.extractall(dest_path, filter="data")
        return dest_path


def resolve(ref: str, *, tag: str | None = None, **registry_kwargs: object) -> Resolved:
    """Convenience one-liner: build a Registry from env/login file and resolve."""
    with Registry(**registry_kwargs) as registry:  # type: ignore[arg-type]
        return registry.resolve(ref, tag=tag)
