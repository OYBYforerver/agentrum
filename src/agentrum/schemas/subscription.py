from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Legacy "new_version" is kept for compatibility with already-created
# subscriptions; "resource.published" is its canonical name.
SubscriptionEvent = Literal["new_version", "resource.published", "resource.deleted"]


class SubscriptionCreateIn(BaseModel):
    kind: str
    namespace: str
    name: str = "*"  # "*" subscribes to the whole namespace catalog (INTERNAL resources only)
    events: list[SubscriptionEvent] = ["new_version"]


class SubscriptionOut(BaseModel):
    id: str
    subscriber_team: str
    kind: str
    namespace: str
    name: str
    events: list
    status: str
    requested_by: str
    approved_by: str | None = None
    created_at: datetime


class SubscriptionListOut(BaseModel):
    items: list[SubscriptionOut]
