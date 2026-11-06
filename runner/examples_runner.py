#!/usr/bin/env python3
"""Watcher for examples/<section>/*.json.

Layout:
  examples/
    k8s/
      kubernetes-osnovy.json
    bash/
      pipelines.json

- New/changed *.json in section folders → POST /api/import?persist=0
- Loose *.json in examples/ root → sort into examples/<tags[0]>/ and import
State: examples/.runner_state.json (path → sha256).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [examples-runner] %(message)s",
)
logger = logging.getLogger("examples_runner")

EXAMPLES_DIR = Path(os.getenv("EXAMPLES_DIR", "/app/examples"))
API_URL = os.getenv("API_URL", "http://app:8000").rstrip("/")
IMPORT_TOKEN = os.getenv("IMPORT_TOKEN", "")
POLL_SECONDS = float(os.getenv("RUNNER_POLL_SECONDS", "5"))
STATE_FILE = EXAMPLES_DIR / ".runner_state.json"
SKIP_DIRS = {"processed", "failed", "__pycache__"}


class RunnerStop(Exception):
    pass


def slugify(text: str) -> str:
    s = (text or "").strip().lower().replace("ё", "e")
    s = re.sub(r"[^a-z0-9а-я]+", "-", s, flags=re.I)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "misc"


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if IMPORT_TOKEN:
        h["X-Import-Token"] = IMPORT_TOKEN
    return h


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Broken state file %s — starting fresh", STATE_FILE)
        return {}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def section_from_payload(doc: dict[str, Any], fallback: str = "misc") -> str:
    tags = doc.get("tags") or []
    if isinstance(tags, list) and tags:
        return slugify(str(tags[0]))
    ext = doc.get("external_id") or ""
    if isinstance(ext, str) and "/" in ext:
        return slugify(ext.split("/", 1)[0])
    return slugify(fallback)


def organize_loose_files(root: Path) -> None:
    """Move examples/*.json into examples/<tag>/ based on JSON tags[0]."""
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Cannot parse loose file %s: %s", path.name, exc)
            continue
        docs = raw if isinstance(raw, list) else [raw]
        if not docs or not isinstance(docs[0], dict):
            logger.error("Loose file %s: expected object or array of objects", path.name)
            continue
        section = section_from_payload(docs[0], fallback=path.stem)
        dest_dir = root / section
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if dest.exists() and dest.resolve() != path.resolve():
            stamp = time.strftime("%Y%m%d_%H%M%S")
            dest = dest_dir / f"{path.stem}_{stamp}.json"
        path.rename(dest)
        logger.info("Sorted %s → %s/%s", path.name, section, dest.name)


def discover_jobs(root: Path) -> list[tuple[str, Path]]:
    jobs: list[tuple[str, Path]] = []
    if not root.is_dir():
        return jobs
    for section_dir in sorted(root.iterdir()):
        if not section_dir.is_dir():
            continue
        name = section_dir.name
        if name.startswith(".") or name in SKIP_DIRS:
            continue
        for path in sorted(section_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            jobs.append((name, path))
    return jobs


def prepare_payload(section: str, path: Path) -> Any:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    prepared = []
    stem = path.stem
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each test must be a JSON object")
        doc = dict(item)
        if not doc.get("external_id"):
            doc["external_id"] = f"{section}/{stem}"
        if not doc.get("title"):
            doc["title"] = stem.replace("-", " ").replace("_", " ")
        tags = list(doc.get("tags") or [])
        if section not in tags and section not in [slugify(str(t)) for t in tags]:
            tags.insert(0, section)
        doc["tags"] = tags
        if "schema_version" not in doc:
            doc["schema_version"] = 1
        prepared.append(doc)
    return prepared[0] if not isinstance(raw, list) else prepared


def import_job(section: str, path: Path) -> dict[str, Any]:
    payload = prepare_payload(section, path)
    # persist=0: file already on disk; don't rewrite from API
    url = f"{API_URL}/api/import?persist=0"
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, headers=_headers(), json=payload)
        if r.status_code >= 400:
            detail = r.text
            try:
                detail = r.json().get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"API {r.status_code}: {detail}")
        return r.json()


def wait_for_api(timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    health = f"{API_URL}/api/health"
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(health)
                if r.status_code == 200 and r.json().get("database"):
                    logger.info("API ready at %s", API_URL)
                    return
        except Exception:
            pass
        time.sleep(2)
    logger.warning("API not healthy after %.0fs — will keep retrying jobs", timeout)


def run_forever() -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    logger.info(
        "Watching %s every %.1fs → %s (%d known files)",
        EXAMPLES_DIR,
        POLL_SECONDS,
        API_URL,
        len(state),
    )
    wait_for_api()

    while True:
        try:
            organize_loose_files(EXAMPLES_DIR)
            for section, path in discover_jobs(EXAMPLES_DIR):
                rel = f"{section}/{path.name}"
                digest = file_hash(path)
                if state.get(rel) == digest:
                    continue
                logger.info("▶ job %s (section=%s)", rel, section)
                try:
                    result = import_job(section, path)
                    imported = result.get("imported") or []
                    titles = ", ".join(
                        f"{x.get('title')} ({x.get('question_count')}q)" for x in imported
                    ) or "ok"
                    state[rel] = digest
                    save_state(state)
                    logger.info("✓ %s → %s", rel, titles)
                except Exception as exc:
                    logger.error("✗ %s: %s", rel, exc)
            time.sleep(POLL_SECONDS)
        except RunnerStop:
            logger.info("Stopped")
            return


def main() -> None:
    def _stop(*_args: object) -> None:
        raise RunnerStop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        run_forever()
    except RunnerStop:
        sys.exit(0)


if __name__ == "__main__":
    main()
