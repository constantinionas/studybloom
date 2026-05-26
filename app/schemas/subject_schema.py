from datetime import datetime

from pydantic import BaseModel, Field


class SubjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=70)


class SubjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=70)


class SubjectResponse(BaseModel):
    id: str
    name: str
    created_at: datetime