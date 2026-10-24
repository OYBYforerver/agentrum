"""Image allowlist for the deployment controller.

Publishing rights effectively mean "code can run in the cluster" — the
allowlist is the guardrail that keeps arbitrary public images out.
"""

import logging

from agentrum import errors

logger = logging.getLogger("agentrum.deploy")


def parse_allowlist(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def image_allowed(image: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True  # dev mode; production must set ARK_IMAGE_ALLOWLIST
    return any(_matches(image, prefix) for prefix in allowlist)


def _matches(image: str, prefix: str) -> bool:
    """Prefix match where the configured prefix always behaves as a path
    boundary: "registry.internal" also admits "registry.internal/team/app",
    but never "registry.internal-evil/...". A trailing slash is added when
    the prefix looks like a bare registry host."""
    if not prefix:
        return False
    host_only = "/" not in prefix
    normalized = f"{prefix}/" if host_only and not prefix.endswith("/") else prefix
    return image.startswith(normalized)


def assert_image_allowed(image: str, allowlist: list[str]) -> None:
    if not image_allowed(image, allowlist):
        raise errors.PermissionDeniedError(
            f"image {image!r} is not on the allowlist "
            f"(allowed prefixes: {', '.join(allowlist)})"
        )


def warn_if_permissive(allowlist: list[str]) -> None:
    """Loud one-shot notice when the controller starts without a guardrail."""
    if not allowlist:
        logger.warning(
            "ARK_IMAGE_ALLOWLIST is empty: deployments may run ANY image "
            "(including public ones). Set it before production use!"
        )
