from pydantic import BaseModel


class TeamCreateIn(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    owner: str | None = None  # username of the project owner (admin); defaults to creator


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
