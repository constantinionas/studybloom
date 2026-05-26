from datetime import datetime
from typing import Any

from pydantic import BaseModel


class QuestionSetResponse(BaseModel):
    id: str
    subject_id: str
    filename: str
    file_type: str
    questions_count: int
    correct_answers_count: int
    warnings: list[Any]
    questions: list[Any]
    storage_path: str | None = None
    status: str
    imported_at: datetime