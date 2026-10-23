"""Image allowlist for the deployment controller.

Publishing rights effectively mean "code can run in the cluster" — the
allowlist is the guardrail that keeps arbitrary public images out.
"""

from agentrum import errors


def parse_allowlist(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def image_allowed(image: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True  # dev mode; production must set ARK_IMAGE_ALLOWLIST
    return any(image.startswith(prefix) for prefix in allowlist)


def assert_image_allowed(image: str, allowlist: list[str]) -> None:
    if not image_allowed(image, allowlist):
        raise errors.PermissionDeniedError(
            f"image {image!r} is not on the allowlist "
            f"(allowed prefixes: {', '.join(allowlist)})"
        )
