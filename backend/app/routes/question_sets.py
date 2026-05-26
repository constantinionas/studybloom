import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from io import BytesIO

from app.config.supabase_client import (
    download_storage_file,
    request_supabase,
    upload_storage_file,
)
from app.schemas.question_set_schema import QuestionSetResponse


router = APIRouter(prefix="/api/question-sets", tags=["Fișiere importate"])


def get_question_set_or_404(question_set_id: str) -> dict:
    question_sets = request_supabase(
        "GET",
        "question_sets",
        params={
            "id": f"eq.{question_set_id}",
            "select": "*",
        },
    )

    if not question_sets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fișierul importat nu a fost găsit.",
        )

    return question_sets[0]


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


def build_storage_path(subject_id: str, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    unique_name = f"{uuid.uuid4()}{extension}"

    return f"{subject_id}/{unique_name}"


@router.get(
    "/subject/{subject_id}",
    response_model=list[QuestionSetResponse],
)
def list_question_sets(subject_id: str) -> list[dict]:
    ensure_subject_exists(subject_id)

    return request_supabase(
        "GET",
        "question_sets",
        params={
            "subject_id": f"eq.{subject_id}",
            "select": "*",
            "order": "imported_at.desc",
        },
    )


@router.get(
    "/{question_set_id}",
    response_model=QuestionSetResponse,
)
def get_question_set(question_set_id: str) -> dict:
    return get_question_set_or_404(question_set_id)


@router.post(
    "",
    response_model=QuestionSetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question_set(
    subject_id: str = Form(...),
    import_result_json: str = Form(...),
    source_file: UploadFile | None = File(default=None),
) -> dict:
    ensure_subject_exists(subject_id)

    try:
        import_result = json.loads(import_result_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datele setului importat nu sunt valide.",
        ) from exc

    filename = str(import_result.get("filename", "")).strip()
    file_type = str(import_result.get("file_type", "")).lower()
    questions = import_result.get("questions", [])
    warnings = import_result.get("warnings", [])

    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Numele fișierului lipsește.",
        )

    if file_type not in {"pdf", "docx"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipul fișierului trebuie să fie PDF sau DOCX.",
        )

    if not isinstance(questions, list) or len(questions) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setul trebuie să conțină cel puțin o întrebare.",
        )

    storage_path: str | None = None

    try:
        if source_file is not None:
            file_content = await source_file.read()

            if file_content:
                storage_path = build_storage_path(subject_id, filename)

                content_type = (
                    source_file.content_type
                    or mimetypes.guess_type(filename)[0]
                    or "application/octet-stream"
                )

                upload_storage_file(
                    storage_path=storage_path,
                    file_content=file_content,
                    content_type=content_type,
                )

        created_sets = request_supabase(
            "POST",
            "question_sets",
            json_data={
                "subject_id": subject_id,
                "filename": filename,
                "file_type": file_type,
                "questions_count": int(
                    import_result.get("questions_count", len(questions))
                ),
                "correct_answers_count": int(
                    import_result.get("correct_answers_count", 0)
                ),
                "warnings": warnings,
                "questions": questions,
                "storage_path": storage_path,
                "status": "processed",
            },
            return_representation=True,
        )

        if not created_sets:
            raise RuntimeError("Setul nu a fost salvat.")

        return created_sets[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fișierul nu a putut fi salvat: {str(exc)}",
        ) from exc

    finally:
        if source_file is not None:
            await source_file.close()


@router.get("/{question_set_id}/source")
def download_original_file(question_set_id: str) -> StreamingResponse:
    question_set = get_question_set_or_404(question_set_id)

    storage_path = question_set.get("storage_path")

    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fișierul original nu este disponibil.",
        )

    try:
        file_content, content_type = download_storage_file(storage_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fișierul original nu a putut fi deschis.",
        ) from exc

    safe_filename = question_set["filename"].replace('"', "")

    return StreamingResponse(
        BytesIO(file_content),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"'
        },
    )


@router.delete(
    "/{question_set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_question_set(question_set_id: str) -> Response:
    get_question_set_or_404(question_set_id)

    try:
        request_supabase(
            "DELETE",
            "question_sets",
            params={"id": f"eq.{question_set_id}"},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fișierul importat nu a putut fi șters.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)