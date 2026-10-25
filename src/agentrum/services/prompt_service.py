"""Prompt template rendering — the one place the variable contract is
enforced, shared by the MCP tool surface and the consumer SDK.

Publish-time spec validation already guarantees template placeholders match
the declared variables; the checks here defend versions published before
that rule and give consumers explicit, actionable errors.
"""

import re

from agentrum import errors

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def render(spec: dict, variables: dict) -> str:
    """Fill the template's declared variables. Unknown variables, missing
    required ones and leftover placeholders are ValidationError — prompt
    contracts are explicit."""
    template = spec.get("template") or ""
    declared = spec.get("variables") or []
    names = {v["name"]: v for v in declared}

    unknown = sorted(set(variables) - set(names))
    if unknown:
        raise errors.ValidationError(f"undeclared template variables: {unknown}")
    missing = sorted(n for n, v in names.items() if v.get("required") and n not in variables)
    if missing:
        raise errors.ValidationError(f"missing required template variables: {missing}")

    def substitute(match: re.Match) -> str:
        name = match.group(1)
        return str(variables[name]) if name in variables else match.group(0)

    rendered = _PLACEHOLDER_RE.sub(substitute, template)
    leftover = sorted(set(_PLACEHOLDER_RE.findall(rendered)))
    if leftover:
        raise errors.ValidationError(
            f"template references variables not declared by the publisher: {leftover}"
        )
    return rendered
