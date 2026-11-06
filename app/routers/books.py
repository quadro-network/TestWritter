from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth import require_import_token
from app.config import get_settings
from app.db import get_db
from app.models import BookJob
from app.services.book_cancel import request_cancel
from app.services.book_worker import ACTIVE, book_worker, finalize_job_cancelled
from app.services.job_log import append_job_log, clear_job_log, read_job_log
from app.services.ollama_client import ollama_ping
from app.services.pdf_clean import slugify

router = APIRouter(prefix="/books", tags=["books"], dependencies=[Depends(require_import_token)])


def _job_out(job: BookJob, *, with_log: bool = False, log_tail: int = 80) -> dict:
    pct = 0.0
    if job.page_count > 0:
        pct = round(100.0 * job.pages_done / job.page_count, 1)
    pdf_name = Path(job.pdf_path).name if job.pdf_path else None
    out = {
        "id": job.id,
        "title": job.title,
        "slug": job.slug,
        "status": job.status,
        "page_count": job.page_count,
        "pages_done": job.pages_done,
        "tests_generated": job.tests_generated,
        "progress_percent": pct,
        "error": job.error,
        "readable_path": job.readable_path,
        "pdf_name": pdf_name,
        "telegram_user_id": job.telegram_user_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "examples_section": f"examples/{job.slug}/",
        "current_step": "",
        "worker_running": book_worker.is_running(job.id),
    }
    log = read_job_log(job.id, tail=log_tail if with_log else 1)
    out["current_step"] = log.get("current_step") or ""
    if with_log:
        out["log_lines"] = log.get("lines") or []
    return out


@router.get("/ollama")
async def ollama_status() -> dict:
    return await ollama_ping()


@router.get("")
def list_books(db: Session = Depends(get_db)) -> dict:
    jobs = db.scalars(select(BookJob).order_by(desc(BookJob.created_at)).limit(50)).all()
    return {"items": [_job_out(j) for j in jobs]}


@router.get("/{job_id}")
def get_book(
    job_id: int,
    log: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(BookJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _job_out(job, with_log=bool(log), log_tail=250)


@router.get("/{job_id}/log")
def get_book_log(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(BookJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    data = read_job_log(job_id, tail=300)
    return {
        "job_id": job_id,
        "status": job.status,
        "current_step": data.get("current_step"),
        "lines": data.get("lines") or [],
        "progress_percent": _job_out(job)["progress_percent"],
        "pages_done": job.pages_done,
        "page_count": job.page_count,
        "tests_generated": job.tests_generated,
    }


@router.post("/upload")
async def upload_book(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    telegram_user_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    name = file.filename or "book.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "only .pdf allowed")

    settings = get_settings()
    books_root = Path(settings.books_dir)
    books_root.mkdir(parents=True, exist_ok=True)

    stem = Path(name).stem
    book_title = (title or stem).strip() or stem
    slug = slugify(book_title, fallback="book")

    tmp_dir = books_root / "_incoming"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_pdf = tmp_dir / f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    with tmp_pdf.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    size = tmp_pdf.stat().st_size

    job = BookJob(
        title=book_title,
        slug=slug,
        status="queued",
        pdf_path=str(tmp_pdf),
        page_count=0,
        pages_done=0,
        tests_generated=0,
        telegram_user_id=telegram_user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_dir = books_root / f"job-{job.id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = job_dir / "source.pdf"
    shutil.move(str(tmp_pdf), str(final_pdf))
    job.pdf_path = str(final_pdf)
    db.commit()

    clear_job_log(job.id)
    append_job_log(
        job.id,
        f"Очередь: PDF «{name}» принят ({size / 1024:.1f} КБ), раздел examples/{slug}/, задача #{job.id}",
    )

    book_worker.enqueue(job.id)
    out = _job_out(job, with_log=True)
    out["accepted"] = True
    out["upload_bytes"] = size
    out["upload_name"] = name
    return out


@router.post("/{job_id}/retry")
def retry_book(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(BookJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status in ACTIVE and book_worker.is_running(job_id):
        raise HTTPException(400, "job already running")
    if job.status in ACTIVE:
        # orphaned "running" row — free it first
        finalize_job_cancelled(job_id, "сброс перед повтором")
        db.refresh(job)
    job.status = "queued"
    job.error = None
    job.pages_done = 0
    job.tests_generated = 0
    job.finished_at = None
    db.commit()
    clear_job_log(job.id)
    append_job_log(job.id, f"Повторный запуск задачи #{job.id}")
    book_worker.enqueue(job.id)
    return _job_out(job, with_log=True)


@router.post("/{job_id}/cancel")
def cancel_book(
    job_id: int,
    force: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(BookJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status not in ACTIVE:
        raise HTTPException(400, f"cannot cancel status={job.status}")

    already = job.status == "cancelling"
    aborted = book_worker.abort_job(job_id)
    running = book_worker.is_running(job_id)

    # orphan (after a rebuild) or a second Stop / force → cancel immediately
    if force or already or not running:
        finalize_job_cancelled(job_id, "остановлено пользователем")
        append_job_log(job_id, "ИТОГ: CANCELLED — принудительная остановка")
        db.refresh(job)
        return _job_out(job, with_log=True)

    job.status = "cancelling"
    db.commit()
    msg = "Остановка… прерываю запрос к модели" if aborted else "Запрос на остановку…"
    append_job_log(job_id, msg)
    db.refresh(job)
    return _job_out(job, with_log=True)


def _delete_job_files(job: BookJob, *, delete_examples: bool = False) -> None:
    settings = get_settings()
    d = Path(settings.books_dir) / f"job-{job.id}"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    if delete_examples and job.slug:
        section = Path(settings.examples_dir) / job.slug
        if section.exists() and section.is_dir():
            shutil.rmtree(section, ignore_errors=True)


@router.delete("/{job_id}")
def delete_book(
    job_id: int,
    delete_examples: int = Query(0, ge=0, le=1),
    force: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(BookJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status in ACTIVE:
        book_worker.abort_job(job_id)
        finalize_job_cancelled(job_id, "удалено пользователем")
        db.refresh(job)
        if not force and book_worker.is_running(job_id):
            raise HTTPException(400, "задача ещё останавливается — нажмите ещё раз или force=1")
    _delete_job_files(job, delete_examples=bool(delete_examples))
    db.delete(job)
    db.commit()
    return {"ok": True, "deleted_id": job_id}


@router.delete("")
def clear_book_history(
    delete_examples: int = Query(0, ge=0, le=1),
    force: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    """Clear history. force=1 (default): stop stuck jobs and delete everything."""
    jobs = db.scalars(select(BookJob).order_by(desc(BookJob.created_at))).all()
    ids: list[int] = []
    for job in jobs:
        if job.status in ACTIVE:
            if not force:
                continue
            book_worker.abort_job(job.id)
            finalize_job_cancelled(job.id, "очистка истории")
            db.refresh(job)
        _delete_job_files(job, delete_examples=bool(delete_examples))
        ids.append(job.id)
        db.delete(job)
    db.commit()
    return {"ok": True, "deleted_ids": ids, "count": len(ids)}
