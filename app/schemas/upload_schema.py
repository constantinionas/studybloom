from pydantic import BaseModel, Field


class AnswerPreview(BaseModel):
    label: str
    text: str
    correct: bool
    source_page: int | None = None


class QuestionPreview(BaseModel):
    number: int
    text: str
    answers: list[AnswerPreview]
    source_pages: list[int] = Field(default_factory=list)

    @property
    def correct_answers_count(self) -> int:
        return sum(1 for answer in self.answers if answer.correct)


class ImportPreviewResponse(BaseModel):
    filename: str
    file_type: str
    questions_count: int
    correct_answers_count: int
    warnings: list[str] = Field(default_factory=list)
    questions: list[QuestionPreview]