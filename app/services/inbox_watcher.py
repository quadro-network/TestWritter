from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.services.import_service import import_one

logger = logging.getLogger("inbox_watcher")


class InboxWatcher:
    def __init__(self) -> None:
        settings = get_settings()
        self.inbox = Path(settings.inbox_dir)
        self.processed = self.inbox / "processed"
        self.failed = self.inbox / "failed"
        self.poll = settings.inbox_poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(parents=True, exist_ok=True)
        self.failed.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="inbox-watcher")
        logger.info("Inbox watcher started on %s", self.inbox)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None
        logger.info("Inbox watcher stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self._process_once)
            except Exception:
                logger.exception("Inbox watcher iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll)
            except asyncio.TimeoutError:
                pass

    def _process_once(self) -> None:
        for path in sorted(self.inbox.glob("*.json")):
            if not path.is_file():
                continue
            logger.info("Importing inbox file %s", path.name)
            try:
                raw = path.read_text(encoding="utf-8")
                with SessionLocal() as db:
                    result = import_one(db, raw)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = self.processed / f"{path.stem}_{stamp}.json"
                shutil.move(str(path), str(dest))
                logger.info(
                    "Imported %s → test id=%s title=%r questions=%s",
                    path.name,
                    result.id,
                    result.title,
                    result.question_count,
                )
            except Exception as exc:
                logger.exception("Failed to import %s", path.name)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = self.failed / f"{path.stem}_{stamp}.json"
                shutil.move(str(path), str(dest))
                err_path = self.failed / f"{path.stem}_{stamp}.error.txt"
                err_path.write_text(str(exc), encoding="utf-8")
