from pydantic import BaseModel


class TeamCreateIn(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None


class TeamOut(BaseModel):
    id: str
    name: str
    display_name: str | None
    description: str | None
    my_role: str | None = None


class MemberAddIn(BaseModel):
    username: str
    role: str


class MemberUpdateIn(BaseModel):
    role: str


class MemberOut(BaseModel):
    username: str
    display_name: str | None
    role: str
