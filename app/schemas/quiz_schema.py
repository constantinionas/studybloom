from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QuizCreateRequest(BaseModel):
    subject_id: str
    question_set_id: str | None = None

    title: str = Field(min_length=1, max_length=120)
    source_filename: str | None = None

    questions: list[Any]
    settings: dict[str, Any]

    is_recovery_quiz: bool = False
    recovery_mode: str | None = None


class QuizRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class QuizResponse(BaseModel):
    id: str
    subject_id: str
    question_set_id: str | None = None

    title: str
    source_filename: str | None = None

    questions: list[Any]
    settings: dict[str, Any]

    is_recovery_quiz: bool
    recovery_mode: str | None = None

    created_at: datetime