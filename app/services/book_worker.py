from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import select

from app.db import SessionLocal
from app.models import BookJob
from app.services.book_cancel import clear_cancel, request_cancel
from app.services.book_pipeline import BookJobCancelled, run_book_job
from app.services.job_log import append_job_log

logger = logging.getLogger("book_worker")

NotifyFn = Callable[[int, str], Awaitable[None] | None]

ACTIVE = ("queued", "extracting", "generating", "cancelling")


class BookWorker:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._notify: NotifyFn | None = None
        self._current_job_id: int | None = None
        self._current_job_task: asyncio.Task | None = None

    def set_notifier(self, fn: NotifyFn | None) -> None:
        self._notify = fn

    def start(self) -> None:
        self._stop.clear()
        reclaim_orphaned_book_jobs()
        self._task = asyncio.create_task(self._run(), name="book-worker")
        logger.info("Book worker started")

    async def stop(self) -> None:
        self._stop.set()
        if self._current_job_task and not self._current_job_task.done():
            self._current_job_task.cancel()
        if self._task:
            await self._queue.put(-1)
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Book worker stopped")

    def enqueue(self, job_id: int) -> None:
        self._queue.put_nowait(job_id)
        logger.info("Enqueued book job %s", job_id)

    def is_running(self, job_id: int) -> bool:
        return self._current_job_id == int(job_id) and bool(
            self._current_job_task and not self._current_job_task.done()
        )

    def abort_job(self, job_id: int) -> bool:
        """Signal cancel + cancel asyncio task if this job is the active one."""
        request_cancel(job_id)
        if self._current_job_id == int(job_id) and self._current_job_task:
            if not self._current_job_task.done():
                self._current_job_task.cancel()
                logger.info("Aborted running book job %s", job_id)
                return True
        return False

    async def _run(self) -> None:
        while not self._stop.is_set():
            job_id = await self._queue.get()
            if job_id < 0:
                continue
            try:
                await self._process(job_id)
            except Exception:
                logger.exception("Unhandled error in book job %s", job_id)

    async def _process(self, job_id: int) -> None:
        async def notify(msg: str):
            if self._notify:
                res = self._notify(job_id, msg)
                if hasattr(res, "__await__"):
                    await res  # type: ignore[misc]

        self._current_job_id = job_id
        job_task = asyncio.create_task(self._run_job(job_id, notify), name=f"book-job-{job_id}")
        self._current_job_task = job_task
        try:
            await job_task
        except asyncio.CancelledError:
            finalize_job_cancelled(job_id, "остановлено (abort)")
            append_job_log(job_id, "ИТОГ: CANCELLED — abort")
            raise
        finally:
            if self._current_job_id == job_id:
                self._current_job_id = None
                self._current_job_task = None

    async def _run_job(self, job_id: int, notify) -> None:
        try:
            with SessionLocal() as db:
                await run_book_job(db, job_id, notify=notify)
        except asyncio.CancelledError:
            finalize_job_cancelled(job_id, "остановлено пользователем (прерван запрос к модели)")
            append_job_log(job_id, "ИТОГ: CANCELLED — прерван запрос")
            raise
        except BookJobCancelled as exc:
            finalize_job_cancelled(job_id, str(exc))
            append_job_log(job_id, f"ИТОГ: CANCELLED — {exc}")


def finalize_job_cancelled(job_id: int, reason: str = "остановлено пользователем") -> None:
    with SessionLocal() as db:
        job = db.get(BookJob, job_id)
        if job and job.status in ACTIVE:
            job.status = "cancelled"
            job.error = reason[:500]
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    clear_cancel(job_id)


def reclaim_orphaned_book_jobs() -> int:
    """After restart nothing is running — stuck statuses become cancelled."""
    n = 0
    with SessionLocal() as db:
        jobs = db.scalars(select(BookJob).where(BookJob.status.in_(ACTIVE))).all()
        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status = "cancelled"
            job.error = "прервано при перезапуске сервиса"
            job.finished_at = now
            n += 1
            clear_cancel(job.id)
            append_job_log(job.id, "ИТОГ: CANCELLED — перезапуск сервиса")
        if n:
            db.commit()
            logger.info("Reclaimed %s orphaned book jobs", n)
    return n


book_worker = BookWorker()
