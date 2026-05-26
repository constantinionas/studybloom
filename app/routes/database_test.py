import uuid

from fastapi import APIRouter, HTTPException

from app.config.supabase_client import request_supabase


router = APIRouter(prefix="/api/test", tags=["Test Supabase"])


@router.get("/supabase")
def test_supabase_connection() -> dict:
    temporary_subject_id: str | None = None
    temporary_subject_name = f"__test_conexiune_{uuid.uuid4().hex[:8]}"

    try:
        settings_data = request_supabase(
            "GET",
            "app_settings",
            params={
                "id": "eq.1",
                "select": "id,manual_review_after_import,theme",
            },
        )

        if not settings_data:
            raise RuntimeError(
                "Nu există rândul implicit din tabela app_settings."
            )

        inserted_subjects = request_supabase(
            "POST",
            "subjects",
            json_data={"name": temporary_subject_name},
            return_representation=True,
        )

        if not inserted_subjects:
            raise RuntimeError("Materia temporară nu a fost inserată.")

        temporary_subject_id = inserted_subjects[0]["id"]

        request_supabase(
            "DELETE",
            "subjects",
            params={"id": f"eq.{temporary_subject_id}"},
        )

        temporary_subject_id = None

        return {
            "status": "ok",
            "message": "Conexiunea cu Supabase funcționează.",
            "database": {
                "app_settings": settings_data[0],
                "insert_delete_subject": "ok",
            },
            "storage": {
                "bucket": "Verifică manual că există bucket-ul privat source-files."
            },
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Testul Supabase a eșuat: {type(exc).__name__}: {str(exc)}",
        ) from exc

    finally:
        if temporary_subject_id is not None:
            try:
                request_supabase(
                    "DELETE",
                    "subjects",
                    params={"id": f"eq.{temporary_subject_id}"},
                )
            except Exception:
                pass