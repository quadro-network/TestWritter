from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings


def job_dir(job_id: int) -> Path:
    root = Path(get_settings().books_dir)
    d = root / f"job-{job_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_job_log(job_id: int, message: str) -> None:
    path = job_dir(job_id) / "progress.log"
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {message}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    step = job_dir(job_id) / "current_step.txt"
    step.write_text(message, encoding="utf-8")


def read_job_log(job_id: int, *, tail: int = 200) -> dict:
    d = job_dir(job_id)
    log_path = d / "progress.log"
    step_path = d / "current_step.txt"
    lines: list[str] = []
    if log_path.exists():
        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = all_lines[-tail:]
    step = step_path.read_text(encoding="utf-8", errors="replace").strip() if step_path.exists() else ""
    return {"lines": lines, "current_step": step, "log_path": str(log_path)}


def clear_job_log(job_id: int) -> None:
    d = job_dir(job_id)
    for name in ("progress.log", "current_step.txt"):
        p = d / name
        if p.exists():
            p.unlink()
