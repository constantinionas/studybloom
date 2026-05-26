import os
from urllib.parse import quote

import httpx
from dotenv import load_dotenv


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "source-files")

if not SUPABASE_URL:
    raise RuntimeError("Lipsește SUPABASE_URL din backend/.env.")

if not SUPABASE_SECRET_KEY:
    raise RuntimeError("Lipsește SUPABASE_SECRET_KEY din backend/.env.")


def get_authorization_headers() -> dict[str, str]:
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
    }

    if SUPABASE_SECRET_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SUPABASE_SECRET_KEY}"

    return headers


def get_rest_headers(*, return_representation: bool = False) -> dict[str, str]:
    headers = {
        **get_authorization_headers(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if return_representation:
        headers["Prefer"] = "return=representation"

    return headers


def get_rest_url(table_name: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table_name}"


def request_supabase(
    method: str,
    table_name: str,
    *,
    params: dict | None = None,
    json_data: dict | list | None = None,
    return_representation: bool = False,
) -> list | dict:
    response = httpx.request(
        method=method,
        url=get_rest_url(table_name),
        headers=get_rest_headers(
            return_representation=return_representation
        ),
        params=params,
        json=json_data,
        timeout=30.0,
    )

    if response.is_error:
        raise RuntimeError(
            f"Supabase a răspuns cu {response.status_code}: {response.text}"
        )

    if not response.content:
        return []

    return response.json()


def upload_storage_file(
    storage_path: str,
    file_content: bytes,
    content_type: str,
) -> None:
    encoded_path = quote(storage_path, safe="/")

    response = httpx.post(
        url=(
            f"{SUPABASE_URL}/storage/v1/object/"
            f"{SUPABASE_STORAGE_BUCKET}/{encoded_path}"
        ),
        headers={
            **get_authorization_headers(),
            "Content-Type": content_type,
            "x-upsert": "false",
        },
        content=file_content,
        timeout=60.0,
    )

    if response.is_error:
        raise RuntimeError(
            f"Fișierul nu a putut fi salvat în Storage: "
            f"{response.status_code}: {response.text}"
        )


def download_storage_file(storage_path: str) -> tuple[bytes, str]:
    encoded_path = quote(storage_path, safe="/")

    response = httpx.get(
        url=(
            f"{SUPABASE_URL}/storage/v1/object/authenticated/"
            f"{SUPABASE_STORAGE_BUCKET}/{encoded_path}"
        ),
        headers=get_authorization_headers(),
        timeout=60.0,
    )

    if response.is_error:
        raise RuntimeError(
            f"Fișierul nu a putut fi descărcat din Storage: "
            f"{response.status_code}: {response.text}"
        )

    content_type = response.headers.get(
        "content-type",
        "application/octet-stream",
    )

    return response.content, content_type