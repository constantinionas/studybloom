from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.config.supabase_client import request_supabase


router = APIRouter(prefix="/api/favorites", tags=["Întrebări favorite"])


class FavoriteQuestionCreateRequest(BaseModel):
    subject_id: str
    question_set_id: str
    question_number: int
    question_text: str
    source_filename: str | None = None
    question_data: dict = Field(default_factory=dict)


class FavoriteQuestionDeleteBySourceRequest(BaseModel):
    subject_id: str
    question_set_id: str
    question_number: int


def get_favorite_by_source(
    subject_id: str,
    question_set_id: str,
    question_number: int,
) -> dict | None:
    favorites = request_supabase(
        "GET",
        "favorite_questions",
        params={
            "subject_id": f"eq.{subject_id}",
            "question_set_id": f"eq.{question_set_id}",
            "question_number": f"eq.{question_number}",
            "select": "*",
            "limit": "1",
        },
    )

    if not favorites:
        return None

    return favorites[0]


@router.get("/subject/{subject_id}")
def list_favorite_questions_by_subject(subject_id: str) -> list[dict]:
    return request_supabase(
        "GET",
        "favorite_questions",
        params={
            "subject_id": f"eq.{subject_id}",
            "select": "*",
            "order": "created_at.desc",
        },
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_favorite_question(payload: FavoriteQuestionCreateRequest) -> dict:
    existing_favorite = get_favorite_by_source(
        payload.subject_id,
        payload.question_set_id,
        payload.question_number,
    )

    if existing_favorite:
        return existing_favorite

    try:
        created_favorites = request_supabase(
            "POST",
            "favorite_questions",
            json_data={
                "subject_id": payload.subject_id,
                "question_set_id": payload.question_set_id,
                "question_number": payload.question_number,
                "question_text": payload.question_text,
                "source_filename": payload.source_filename,
                "question_data": payload.question_data,
            },
            return_representation=True,
        )

        if not created_favorites:
            raise RuntimeError("Întrebarea favorită nu a fost salvată.")

        return created_favorites[0]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Întrebarea nu a putut fi adăugată la favorite: {str(exc)}",
        ) from exc


@router.delete("/by-source", status_code=status.HTTP_204_NO_CONTENT)
def delete_favorite_question_by_source(
    payload: FavoriteQuestionDeleteBySourceRequest,
) -> Response:
    try:
        request_supabase(
            "DELETE",
            "favorite_questions",
            params={
                "subject_id": f"eq.{payload.subject_id}",
                "question_set_id": f"eq.{payload.question_set_id}",
                "question_number": f"eq.{payload.question_number}",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Întrebarea nu a putut fi eliminată din favorite.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.delete("/{favorite_question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_favorite_question(favorite_question_id: str) -> Response:
    try:
        request_supabase(
            "DELETE",
            "favorite_questions",
            params={
                "id": f"eq.{favorite_question_id}",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Întrebarea nu a putut fi eliminată din favorite.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


