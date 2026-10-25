"""Shared status-condition upsert for resources.

Several controllers write conditions onto the same resource over time
(probe health, skill drift, reconcile state). Replacing the whole list
would silently drop the others' output; every writer goes through
`merge_condition` instead, which upserts by condition type.
"""

from agentrum.db import models

# Timestamps that differ on every write even when the state is unchanged;
# change detection ignores them so a steady state does not rewrite the row
# (and its updated_at) every tick.
_VOLATILE_KEYS = ("last_transition", "checked_at")


def _stable(condition: dict) -> dict:
    return {k: v for k, v in condition.items() if k not in _VOLATILE_KEYS}


def merge_condition(resource: models.Resource, condition: dict) -> bool:
    """Upsert one condition by type, preserving conditions written by other
    controllers. Returns True when the stored status actually changed
    (ignoring the volatile timestamps), so callers can skip no-op writes."""
    status = dict(resource.status or {})
    conditions = [
        dict(c) for c in status.get("conditions", []) if isinstance(c, dict) and c.get("type")
    ]
    existing = next((c for c in conditions if c["type"] == condition["type"]), None)
    if existing is not None and _stable(existing) == _stable(condition):
        return False
    conditions = [c for c in conditions if c["type"] != condition["type"]]
    conditions.append(condition)
    resource.status = {**status, "conditions": conditions}
    return True
