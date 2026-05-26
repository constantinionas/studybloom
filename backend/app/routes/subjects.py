from fastapi import APIRouter, HTTPException, Response, status

from app.config.supabase_client import request_supabase
from app.schemas.subject_schema import (
    SubjectCreateRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)


router = APIRouter(prefix="/api/subjects", tags=["Materii"])


def normalize_subject_name(name: str) -> str:
    return " ".join(name.strip().split())


def get_subject_or_404(subject_id: str) -> dict:
    subjects = request_supabase(
        "GET",
        "subjects",
        params={
            "id": f"eq.{subject_id}",
            "select": "id,name,created_at",
        },
    )

    if not subjects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Materia nu a fost găsită.",
        )

    return subjects[0]


@router.get("", response_model=list[SubjectResponse])
def list_subjects() -> list[dict]:
    return request_supabase(
        "GET",
        "subjects",
        params={
            "select": "id,name,created_at",
            "order": "created_at.desc",
        },
    )


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: str) -> dict:
    return get_subject_or_404(subject_id)


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subject(payload: SubjectCreateRequest) -> dict:
    subject_name = normalize_subject_name(payload.name)

    if not subject_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Introdu numele materiei.",
        )

    try:
        created_subjects = request_supabase(
            "POST",
            "subjects",
            json_data={"name": subject_name},
            return_representation=True,
        )
    except RuntimeError as exc:
        error_text = str(exc)

        if "23505" in error_text or "duplicate key" in error_text.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Există deja o materie cu acest nume.",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Materia nu a putut fi creată.",
        ) from exc

    return created_subjects[0]


@router.patch("/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: str, payload: SubjectUpdateRequest) -> dict:
    get_subject_or_404(subject_id)

    subject_name = normalize_subject_name(payload.name)

    if not subject_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Introdu numele materiei.",
        )

    try:
        updated_subjects = request_supabase(
            "PATCH",
            "subjects",
            params={"id": f"eq.{subject_id}"},
            json_data={"name": subject_name},
            return_representation=True,
        )
    except RuntimeError as exc:
        error_text = str(exc)

        if "23505" in error_text or "duplicate key" in error_text.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Există deja o materie cu acest nume.",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Materia nu a putut fi redenumită.",
        ) from exc

    if not updated_subjects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Materia nu a fost găsită.",
        )

    return updated_subjects[0]


@router.delete(
    "/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_subject(subject_id: str) -> Response:
    get_subject_or_404(subject_id)

    try:
        request_supabase(
            "DELETE",
            "subjects",
            params={"id": f"eq.{subject_id}"},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Materia nu a putut fi ștearsă.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)