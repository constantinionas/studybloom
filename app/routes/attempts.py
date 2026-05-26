from fastapi import APIRouter, HTTPException, Response, status

from app.config.supabase_client import request_supabase
from app.schemas.attempt_schema import (
    AttemptCreateRequest,
    AttemptResponse,
)


router = APIRouter(prefix="/api/attempts", tags=["Rezultate"])


def ensure_subject_exists(subject_id: str) -> None:
    subjects = request_supabase(
        "GET",
        "subjects",
        params={
            "id": f"eq.{subject_id}",
            "select": "id",
        },
    )

    if not subjects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Materia nu a fost găsită.",
        )


def ensure_quiz_exists(quiz_id: str | None) -> None:
    if not quiz_id:
        return

    quizzes = request_supabase(
        "GET",
        "quizzes",
        params={
            "id": f"eq.{quiz_id}",
            "select": "id",
        },
    )

    if not quizzes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testul nu a fost găsit.",
        )


def ensure_question_set_exists(question_set_id: str | None) -> None:
    if not question_set_id:
        return

    question_sets = request_supabase(
        "GET",
        "question_sets",
        params={
            "id": f"eq.{question_set_id}",
            "select": "id",
        },
    )

    if not question_sets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setul de grile nu a fost găsit.",
        )


def get_attempt_or_404(attempt_id: str) -> dict:
    attempts = request_supabase(
        "GET",
        "quiz_attempts",
        params={
            "id": f"eq.{attempt_id}",
            "select": "*",
        },
    )

    if not attempts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rezultatul nu a fost găsit.",
        )

    return attempts[0]


@router.get(
    "/subject/{subject_id}",
    response_model=list[AttemptResponse],
)
def list_attempts_by_subject(subject_id: str) -> list[dict]:
    ensure_subject_exists(subject_id)

    return request_supabase(
        "GET",
        "quiz_attempts",
        params={
            "subject_id": f"eq.{subject_id}",
            "select": "*",
            "order": "completed_at.desc",
        },
    )


@router.post(
    "",
    response_model=AttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_attempt(payload: AttemptCreateRequest) -> dict:
    ensure_subject_exists(payload.subject_id)
    ensure_question_set_exists(payload.question_set_id)
    ensure_quiz_exists(payload.quiz_id)

    if (
        payload.fully_correct_count
        + payload.partially_correct_count
        + payload.wrong_count
        != payload.total_questions
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Totalul răspunsurilor evaluate nu corespunde numărului de întrebări.",
        )

    try:
        created_attempts = request_supabase(
            "POST",
            "quiz_attempts",
            json_data={
                "subject_id": payload.subject_id,
                "question_set_id": payload.question_set_id,
                "quiz_id": payload.quiz_id,
                "quiz_title": payload.quiz_title,
                "source_filename": payload.source_filename,
                "settings": payload.settings,
                "total_questions": payload.total_questions,
                "earned_points": payload.earned_points,
                "percentage": payload.percentage,
                "fully_correct_count": payload.fully_correct_count,
                "partially_correct_count": payload.partially_correct_count,
                "wrong_count": payload.wrong_count,
                "result_message": payload.result_message,
                "progress_message": payload.progress_message,
                "progress_difference": payload.progress_difference,
                "special_reward_unlocked": payload.special_reward_unlocked,
                "question_results": payload.question_results,
                "questions": payload.questions,
            },
            return_representation=True,
        )

        if not created_attempts:
            raise RuntimeError("Rezultatul nu a fost salvat.")

        return created_attempts[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rezultatul nu a putut fi salvat: {str(exc)}",
        ) from exc


@router.delete(
    "/{attempt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attempt(attempt_id: str) -> Response:
    get_attempt_or_404(attempt_id)

    try:
        request_supabase(
            "DELETE",
            "quiz_attempts",
            params={"id": f"eq.{attempt_id}"},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rezultatul nu a putut fi șters.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)