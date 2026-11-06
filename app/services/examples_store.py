from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("examples_store")


def examples_root() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "examples_dir", None) or "/app/examples")


def slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("ё", "e")
    s = re.sub(r"[^a-z0-9а-я]+", "-", s, flags=re.I)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "test"


def section_from_doc(doc: dict[str, Any]) -> str:
    ext = doc.get("external_id") or ""
    if isinstance(ext, str) and "/" in ext:
        return slugify(ext.split("/", 1)[0])

    tags = [slugify(str(t)) for t in (doc.get("tags") or []) if str(t).strip()]
    root = examples_root()
    # prefer an existing section folder that matches a tag
    for tag in tags:
        if (root / tag).is_dir():
            return tag
    if tags:
        return tags[0]
    return "misc"


def filename_from_doc(doc: dict[str, Any], section: str) -> str:
    ext = doc.get("external_id")
    if isinstance(ext, str) and ext.strip():
        # k8s/networking → networking
        stem = ext.strip().split("/")[-1]
        stem = stem.removesuffix(".json")
        return f"{slugify(stem)}.json"
    title = doc.get("title") or "test"
    return f"{slugify(str(title))}.json"


def save_docs_to_examples(raw: Any) -> list[str]:
    """Persist imported JSON under examples/<tag>/<file>.json. Returns relative paths."""
    root = examples_root()
    root.mkdir(parents=True, exist_ok=True)
    items = raw if isinstance(raw, list) else [raw]
    saved: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        section = section_from_doc(item)
        name = filename_from_doc(item, section)
        folder = root / section
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        # ensure tag[0] matches folder
        tags = list(item.get("tags") or [])
        if section not in [slugify(str(t)) for t in tags]:
            tags.insert(0, section)
            item = {**item, "tags": tags}
        if not item.get("external_id"):
            item = {**item, "external_id": f"{section}/{path.stem}"}
        path.write_text(
            json.dumps(item, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rel = f"{section}/{name}"
        saved.append(rel)
        logger.info("Saved example %s", rel)
    return saved
