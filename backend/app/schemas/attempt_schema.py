from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AttemptCreateRequest(BaseModel):
    subject_id: str
    question_set_id: str | None = None
    quiz_id: str | None = None

    quiz_title: str = Field(min_length=1, max_length=120)
    source_filename: str | None = None

    settings: dict[str, Any]

    total_questions: int = Field(gt=0)
    earned_points: float = Field(ge=0)
    percentage: int = Field(ge=0, le=100)

    fully_correct_count: int = Field(ge=0)
    partially_correct_count: int = Field(ge=0)
    wrong_count: int = Field(ge=0)

    result_message: str | None = None
    progress_message: str | None = None
    progress_difference: int | None = None
    special_reward_unlocked: bool = False

    question_results: list[Any]
    questions: list[Any]


class AttemptResponse(BaseModel):
    id: str
    subject_id: str
    question_set_id: str | None = None
    quiz_id: str | None = None

    quiz_title: str
    source_filename: str | None = None

    settings: dict[str, Any]

    total_questions: int
    earned_points: float
    percentage: int

    fully_correct_count: int
    partially_correct_count: int
    wrong_count: int

    result_message: str | None = None
    progress_message: str | None = None
    progress_difference: int | None = None
    special_reward_unlocked: bool

    question_results: list[Any]
    questions: list[Any]

    completed_at: datetime