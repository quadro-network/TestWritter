from __future__ import annotations

import re
from pathlib import Path


def _normalize_page_text(raw: str) -> str:
    text = raw.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # join hyphenated line breaks: word-\nword → wordword
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # collapse 3+ newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # trim trailing spaces per line
    lines = [ln.strip() for ln in text.split("\n")]
    # drop likely page-number-only lines
    cleaned: list[str] = []
    for ln in lines:
        if re.fullmatch(r"\d{1,4}", ln):
            continue
        if re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", ln):
            continue
        cleaned.append(ln)
    text = "\n".join(cleaned)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    """Return list of {page, text} with cleaned text for LLM."""
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    pages: list[dict] = []
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            raw = page.get_text("text") or ""
            text = _normalize_page_text(raw)
            pages.append({"page": i + 1, "text": text, "chars": len(text)})
    finally:
        doc.close()
    return pages


def pages_to_readable_markdown(title: str, pages: list[dict]) -> str:
    parts = [f"# {title}", "", f"_Страниц: {len(pages)}_", ""]
    for p in pages:
        parts.append(f"## Страница {p['page']}")
        parts.append("")
        body = p["text"] or "_(пусто / скан без текста)_"
        parts.append(body)
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def slugify(text: str, fallback: str = "book") -> str:
    import re as _re

    s = (text or "").strip().lower().replace("ё", "e")
    s = _re.sub(r"[^a-z0-9а-я]+", "-", s, flags=_re.I)
    s = _re.sub(r"-+", "-", s).strip("-")
    return s[:80] or fallback
