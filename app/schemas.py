from pydantic import BaseModel

class ProjectBase(BaseModel):
    group_no: int
    project_title: str
    guide_name: str
    usn: list[str]
    name: list[str]
    outcomes: str | None = None
    proof_link: str | None = None

    class Config:
        orm_mode = True