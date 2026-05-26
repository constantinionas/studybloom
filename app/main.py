from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.database_test import router as database_test_router
from app.routes.subjects import router as subjects_router
from app.routes.upload import router as upload_router
from app.routes.question_sets import router as question_sets_router
from app.routes.attempts import router as attempts_router
from app.routes.quizzes import router as quizzes_router


app = FastAPI(
    title="StudyBloom API",
    description="Backend pentru importarea grilelor și generarea quizurilor.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(database_test_router)
app.include_router(subjects_router)
app.include_router(question_sets_router)
app.include_router(quizzes_router)
app.include_router(attempts_router)


@app.get("/")
def root() -> dict:
    return {
        "message": "StudyBloom API funcționează.",
        "docs": "/docs",
    }


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "StudyBloom API",
    }