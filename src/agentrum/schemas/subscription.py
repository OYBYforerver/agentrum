from datetime import datetime

from pydantic import BaseModel


class SubscriptionCreateIn(BaseModel):
    kind: str
    namespace: str
    name: str = "*"  # "*" subscribes to the whole namespace catalog
    events: list[str] = ["new_version"]


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
