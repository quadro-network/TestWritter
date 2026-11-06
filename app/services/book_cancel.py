from __future__ import annotations

import threading

_lock = threading.Lock()
_cancelled: set[int] = set()


def request_cancel(job_id: int) -> None:
    with _lock:
        _cancelled.add(int(job_id))


def clear_cancel(job_id: int) -> None:
    with _lock:
        _cancelled.discard(int(job_id))


def is_cancelled(job_id: int) -> bool:
    with _lock:
        return int(job_id) in _cancelled
