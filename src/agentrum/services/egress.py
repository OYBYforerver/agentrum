"""Egress guard for server-initiated outbound requests.

Publishers control where the registry connects next: git URLs at publish
time (SHA pinning, entrypoint snapshot, drift checks), MCPServer endpoints
for health probes, and skill repositories for content delivery. Without a
guard that is an SSRF surface — the registry pod can be aimed at in-cluster
services, at itself, or at cloud metadata endpoints.

Policy:
- Schemes: http, https, git. `file://` and bare local paths are refused
  unless ARK_EGRESS_ALLOW_FILE_SOURCES=true (local development / test
  fixtures only).
- Loopback and link-local ranges (169.254.0.0/10 includes the cloud metadata
  endpoints) and the unspecified address are always refused unless
  ARK_EGRESS_ALLOW_LOOPBACK=true.
- Private ranges (RFC1918 etc.) stay reachable by default — internal git
  registries are the norm for enterprise deployments; set
  ARK_EGRESS_ALLOW_PRIVATE_ADDRESSES=false to refuse them too.

Residual risk, on record: the hostname is resolved and checked here, then
connected to by the HTTP/git client — a DNS answer that changes between the
two (rebinding) is not prevented. Deployments that care run the registry
behind an egress-filtering network policy regardless.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from agentrum import errors
from agentrum.config import get_settings

_ALLOWED_SCHEMES = {"http", "https", "git"}


def _blocked_reason(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_loopback: bool,
    allow_private: bool,
) -> str | None:
    """Human-readable reason when this address is off-limits, else None."""
    if ip.is_unspecified:
        return "an unspecified address"
    if allow_loopback:
        return None
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address (cloud metadata range)"
    if not allow_private and ip.is_private:
        return "a private address"
    return None


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str, purpose: str, settings) -> None:  # type: ignore[no-untyped-def]
    reason = _blocked_reason(
        ip,
        allow_loopback=settings.egress_allow_loopback,
        allow_private=settings.egress_allow_private_addresses,
    )
    if reason:
        raise errors.ValidationError(f"{purpose}: {host} is {reason} — refused")


def validate_outbound_url(url: str, *, purpose: str = "outbound request") -> str:
    """Validate a URL the server is about to connect to. Returns the URL
    unchanged; raises ValidationError when the target is off-limits."""
    settings = get_settings()
    raw = (url or "").strip()
    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()

    if scheme == "file" or (not scheme and raw):
        if settings.egress_allow_file_sources:
            return raw
        raise errors.ValidationError(
            f"{purpose}: file/local git sources are disabled on this server"
        )
    if scheme not in _ALLOWED_SCHEMES or not parts.hostname:
        raise errors.ValidationError(
            f"{purpose}: URL must be http(s)://… or git://… with an explicit host"
        )

    host = parts.hostname
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        _check_ip(addr, host, purpose, settings)
        return raw

    # Hostname: every resolved address must pass, so `localhost` or a name
    # that only resolves inside the cluster cannot be used to reach the pod.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise errors.ValidationError(f"{purpose}: host {host!r} does not resolve") from None
    for info in infos:
        _check_ip(ipaddress.ip_address(info[4][0]), host, purpose, settings)
    return raw
