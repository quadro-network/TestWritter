from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import check_db
from app.routers import attempts, books, importer, review, stats, tests
from app.schemas import HealthOut
from app.services.book_worker import book_worker
from app.services.inbox_watcher import InboxWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
watcher = InboxWatcher()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    Path(settings.books_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.examples_dir).mkdir(parents=True, exist_ok=True)
    watcher.start()
    book_worker.start()
    logger.info("Application started")
    yield
    await book_worker.stop()
    await watcher.stop()


app = FastAPI(title="Tests", version="1.0.0", lifespan=lifespan)
app.include_router(tests.router, prefix="/api")
app.include_router(attempts.router, prefix="/api")
app.include_router(importer.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(books.router, prefix="/api")


@app.get("/api/health", response_model=HealthOut)
def health() -> HealthOut:
    ok = check_db()
    return HealthOut(status="ok" if ok else "degraded", database=ok)


@app.get("/api/config")
def public_config() -> dict:
    settings = get_settings()
    return {
        "web_url": settings.web_url,
        "import_token": settings.import_token,
        "ollama_model": settings.ollama_model,
        "ollama_base_url": settings.ollama_base_url,
    }


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
