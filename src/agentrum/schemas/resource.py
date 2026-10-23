from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ResourceApplyIn(BaseModel):
    spec: dict[str, Any]
    tag: str | None = None
    labels: dict[str, str] | None = None
    description: str | None = None
    visibility: Literal["internal", "restricted"] | None = None


class ResourceVersionOut(BaseModel):
    version: int
    tag: str | None
    spec: dict[str, Any]
    published_by: str
    created_at: datetime


class ResourceOut(BaseModel):
    kind: str
    namespace: str
    name: str
    visibility: str
    labels: dict[str, Any]
    description: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    latest_version: ResourceVersionOut | None = None


class ResourceListOut(BaseModel):
    items: list[ResourceOut]
    total: int
    limit: int
    offset: int
