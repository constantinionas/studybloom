from fastapi import APIRouter, HTTPException, Response, status

from app.config.supabase_client import request_supabase
from app.schemas.quiz_schema import (
    QuizCreateRequest,
    QuizRenameRequest,
    QuizResponse,
)


router = APIRouter(prefix="/api/quizzes", tags=["Teste create"])


def normalize_title(title: str) -> str:
    return " ".join(title.strip().split())


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


def get_quiz_or_404(quiz_id: str) -> dict:
    quizzes = request_supabase(
        "GET",
        "quizzes",
        params={
            "id": f"eq.{quiz_id}",
            "select": "*",
        },
    )

    if not quizzes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testul nu a fost găsit.",
        )

    return quizzes[0]


@router.get(
    "/subject/{subject_id}",
    response_model=list[QuizResponse],
)
def list_quizzes_by_subject(subject_id: str) -> list[dict]:
    ensure_subject_exists(subject_id)

    return request_supabase(
        "GET",
        "quizzes",
        params={
            "subject_id": f"eq.{subject_id}",
            "select": "*",
            "order": "created_at.desc",
        },
    )


@router.post(
    "",
    response_model=QuizResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_quiz(payload: QuizCreateRequest) -> dict:
    ensure_subject_exists(payload.subject_id)
    ensure_question_set_exists(payload.question_set_id)

    title = normalize_title(payload.title)

    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Introdu numele testului.",
        )

    if not payload.questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Testul trebuie să conțină cel puțin o întrebare.",
        )

    if payload.is_recovery_quiz:
        allowed_modes = {"all", "wrong", "repeated"}

        if payload.recovery_mode not in allowed_modes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tipul testului de recuperare nu este valid.",
            )

    try:
        created_quizzes = request_supabase(
            "POST",
            "quizzes",
            json_data={
                "subject_id": payload.subject_id,
                "question_set_id": payload.question_set_id,
                "title": title,
                "source_filename": payload.source_filename,
                "questions": payload.questions,
                "settings": payload.settings,
                "is_recovery_quiz": payload.is_recovery_quiz,
                "recovery_mode": payload.recovery_mode,
            },
            return_representation=True,
        )

        if not created_quizzes:
            raise RuntimeError("Testul nu a fost salvat.")

        return created_quizzes[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Testul nu a putut fi salvat: {str(exc)}",
        ) from exc


@router.patch(
    "/{quiz_id}/title",
    response_model=QuizResponse,
)
def rename_quiz(quiz_id: str, payload: QuizRenameRequest) -> dict:
    get_quiz_or_404(quiz_id)

    title = normalize_title(payload.title)

    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Numele testului nu poate fi gol.",
        )

    try:
        updated_quizzes = request_supabase(
            "PATCH",
            "quizzes",
            params={"id": f"eq.{quiz_id}"},
            json_data={"title": title},
            return_representation=True,
        )

        # Păstrăm același nume și în rezultatele deja salvate.
        request_supabase(
            "PATCH",
            "quiz_attempts",
            params={"quiz_id": f"eq.{quiz_id}"},
            json_data={"quiz_title": title},
        )

        if not updated_quizzes:
            raise RuntimeError("Testul nu a fost redenumit.")

        return updated_quizzes[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Testul nu a putut fi redenumit: {str(exc)}",
        ) from exc


@router.delete(
    "/{quiz_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_quiz(quiz_id: str) -> Response:
    get_quiz_or_404(quiz_id)

    try:
        # În aplicație, ștergerea testului elimină și istoricul lui.
        request_supabase(
            "DELETE",
            "quiz_attempts",
            params={"quiz_id": f"eq.{quiz_id}"},
        )

        request_supabase(
            "DELETE",
            "quizzes",
            params={"id": f"eq.{quiz_id}"},
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Testul nu a putut fi șters.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)