import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.upload_schema import ImportPreviewResponse
from app.services.docx_parser import parse_docx_questions
from app.services.pdf_parser import parse_pdf_questions


router = APIRouter(prefix="/api/import", tags=["Import"])


def safely_delete_temp_file(file_path: Path) -> None:
    """
    Șterge fișierul temporar.
    Pe Windows, uneori fișierul rămâne blocat foarte scurt după citire.
    """
    for attempt in range(3):
        try:
            file_path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.15)


@router.post("/preview", response_model=ImportPreviewResponse)
async def preview_import(file: UploadFile = File(...)) -> ImportPreviewResponse:
    filename = file.filename or "fisier"
    extension = Path(filename).suffix.lower()

    if extension not in {".pdf", ".docx"}:
        raise HTTPException(
            status_code=400,
            detail="Format neacceptat. Încarcă un fișier PDF sau DOCX.",
        )

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = Path(temp_file.name)

        await file.close()

        if extension == ".pdf":
            questions, warnings = parse_pdf_questions(temp_path)
            file_type = "pdf"
        else:
            questions, warnings = parse_docx_questions(temp_path)
            file_type = "docx"

        correct_answers_count = sum(
            1
            for question in questions
            for answer in question.answers
            if answer.correct
        )

        return ImportPreviewResponse(
            filename=filename,
            file_type=file_type,
            questions_count=len(questions),
            correct_answers_count=correct_answers_count,
            warnings=warnings,
            questions=questions,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Fișierul nu a putut fi procesat: {type(exc).__name__}: {str(exc)}",
        ) from exc

    finally:
        await file.close()

        if temp_path is not None:
            safely_delete_temp_file(temp_path)