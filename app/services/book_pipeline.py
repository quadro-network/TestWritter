from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BookJob
from app.schemas import QuestionIn, TestIn
from app.services.book_cancel import clear_cancel, is_cancelled
from app.services.job_log import append_job_log, clear_job_log, job_dir
from app.services.ollama_client import OllamaError, ollama_chat_json, ollama_ping
from app.services.pdf_clean import extract_pdf_pages, pages_to_readable_markdown, slugify


class BookJobCancelled(Exception):
    pass

logger = logging.getLogger("book_pipeline")

ProgressCb = Callable[[str], Awaitable[None] | None]


SYSTEM_PROMPT = """Ты — автор учебных тестов для DevOps/IT.
Верни ТОЛЬКО один JSON-объект теста (schema_version 1), без markdown и пояснений.
ОБЯЗАТЕЛЬНО у КАЖДОГО вопроса есть ВСЕ поля:
type, topic, difficulty, question, options, correct, explanation.
Правила:
- schema_version: 1
- title, description, tags[], questions[]
- type: single | multiple | true_false
- options: объект из 2–8 пар "ключ":"текст" (не массив!). Для true_false всегда {"A":"Верно","B":"Неверно"}
- correct: массив ключей из options. single/true_false → ровно ["A"] (один ключ). multiple → ≥1
- explanation: непустая строка (почему ответ верный)
- difficulty: целое 1–5
- язык: русский; факты только из фрагмента
Пример одного вопроса:
{"type":"single","topic":"Docker","difficulty":2,"question":"...","options":{"A":"...","B":"...","C":"..."},"correct":["A"],"explanation":"..."}
"""


def _unique_topic_path(section_dir: Path, topic_slug: str, part: int) -> Path:
    base = section_dir / f"{topic_slug}.json"
    if not base.exists():
        return base
    return section_dir / f"{topic_slug}-part{part}.json"


def _chunk_pages(pages: list[dict], chunk_size: int) -> list[list[dict]]:
    return [pages[i : i + chunk_size] for i in range(0, len(pages), chunk_size)]


def _as_options(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, dict) and raw:
        out: dict[str, str] = {}
        for i, (k, v) in enumerate(raw.items()):
            key = str(k).strip() or chr(65 + i)
            text = v if isinstance(v, str) else (v.get("text") if isinstance(v, dict) else str(v))
            text = str(text or "").strip()
            if text:
                out[key] = text
        return out or None
    if isinstance(raw, list) and len(raw) >= 2:
        out = {}
        for i, item in enumerate(raw):
            key = chr(65 + i)
            if isinstance(item, dict):
                key = str(item.get("key") or item.get("id") or key)
                text = str(item.get("text") or item.get("label") or item.get("value") or "").strip()
            else:
                text = str(item).strip()
            if text:
                out[key] = text
        return out or None
    return None


def _sanitize_question(q: Any, topic_fallback: str) -> dict[str, Any] | None:
    """Repair typical broken LLM JSON, or drop the question."""
    if not isinstance(q, dict):
        return None
    qtype = str(q.get("type") or "single").strip().lower().replace("-", "_")
    if qtype in ("truefalse", "bool", "boolean"):
        qtype = "true_false"
    if qtype not in ("single", "multiple", "true_false"):
        qtype = "single"

    question = str(q.get("question") or q.get("text") or "").strip()
    if not question:
        return None

    options = _as_options(q.get("options"))
    if qtype == "true_false" and (not options or len(options) < 2):
        options = {"A": "Верно", "B": "Неверно"}
    if not options or len(options) < 2:
        return None
    # trim to 8
    if len(options) > 8:
        options = dict(list(options.items())[:8])

    keys = list(options.keys())
    correct_raw = q.get("correct")
    if isinstance(correct_raw, str):
        correct_raw = [correct_raw]
    if not isinstance(correct_raw, list):
        correct_raw = []
    correct = [str(c) for c in correct_raw if str(c) in options]
    # sometimes the model writes the option text instead of the key
    if not correct:
        for c in correct_raw:
            cs = str(c).strip().lower()
            for k, text in options.items():
                if text.strip().lower() == cs or k.lower() == cs:
                    correct.append(k)
                    break
    if qtype in ("single", "true_false"):
        if not correct:
            correct = [keys[0]]
        else:
            correct = [correct[0]]
    else:
        if not correct:
            correct = [keys[0]]

    explanation = str(q.get("explanation") or q.get("explain") or "").strip()
    if not explanation:
        explanation = f"Правильный ответ: {', '.join(options[c] for c in correct)}."

    try:
        difficulty = int(q.get("difficulty") or 2)
    except (TypeError, ValueError):
        difficulty = 2
    difficulty = max(1, min(5, difficulty))

    topic = str(q.get("topic") or topic_fallback).strip() or topic_fallback

    cleaned: dict[str, Any] = {
        "type": qtype,
        "topic": topic,
        "difficulty": difficulty,
        "question": question,
        "options": options,
        "correct": correct,
        "explanation": explanation,
    }
    oe = q.get("option_explanations")
    if isinstance(oe, dict):
        cleaned["option_explanations"] = {
            str(k): str(v) for k, v in oe.items() if str(k) in options and str(v).strip()
        }
    code = q.get("code")
    if isinstance(code, dict) and code.get("language") and code.get("content"):
        cleaned["code"] = {
            "language": str(code["language"]),
            "content": str(code["content"]),
        }

    try:
        return QuestionIn.model_validate(cleaned).model_dump(mode="json")
    except ValidationError:
        return None


def _sanitize_test_doc(raw: dict[str, Any], *, topic_fallback: str, min_questions: int) -> dict[str, Any]:
    qs_in = raw.get("questions") or []
    if not isinstance(qs_in, list):
        qs_in = []
    good: list[dict[str, Any]] = []
    dropped = 0
    for q in qs_in:
        fixed = _sanitize_question(q, topic_fallback)
        if fixed:
            good.append(fixed)
        else:
            dropped += 1
    if len(good) < min_questions:
        raise OllamaError(
            f"after sanitize only {len(good)} valid questions (need ≥{min_questions}), dropped {dropped}"
        )
    raw = {**raw, "questions": good}
    if dropped:
        logger.info("sanitized test: kept %s, dropped %s broken questions", len(good), dropped)
    return TestIn.model_validate(raw).model_dump(mode="json")


async def generate_test_for_chunk(
    *,
    book_title: str,
    book_slug: str,
    part_no: int,
    pages: list[dict],
    questions_n: int,
) -> dict[str, Any]:
    page_nos = [int(p["page"]) for p in pages]
    # model context is ~4k; Ollama already cut a 4919-token prompt down to 2050 — keep the text shorter
    joined_parts = []
    budget = 4500
    per_page = max(400, budget // max(1, len(pages)))
    for p in pages:
        block = f"### Стр. {p['page']}\n{(p.get('text') or '').strip()[:per_page]}"
        if sum(len(x) for x in joined_parts) + len(block) > budget:
            break
        joined_parts.append(block)
    body = "\n\n".join(joined_parts)
    page_range = f"{page_nos[0]}-{page_nos[-1]}"
    user = f"""Книга: «{book_title}»
Фрагмент: страницы {page_range} (часть {part_no}).

Сделай ОДИН тест (один JSON) по этому фрагменту.
external_id: "{book_slug}/part-{part_no}"
tags: ["{book_slug}", "book", "part-{part_no}"]
Число вопросов: {questions_n} (допустимо {max(8, questions_n - 3)}–{questions_n + 2}).
У КАЖДОГО вопроса обязательно: type, topic, difficulty, question, options (объект!), correct (массив ключей), explanation.
title: «{book_title}: …» — уточни тему части.

Текст:
---
{body}
---
"""
    raw = await ollama_chat_json(SYSTEM_PROMPT, user, temperature=0.35)
    if isinstance(raw, list):
        raw = raw[0]
    if not isinstance(raw, dict):
        raise OllamaError("model returned non-object JSON")
    raw.setdefault("schema_version", 1)
    raw.setdefault("title", f"{book_title}: часть {part_no}")
    if not str(raw.get("title") or "").strip():
        raw["title"] = f"{book_title}: часть {part_no}"
    raw["external_id"] = f"{book_slug}/part-{part_no}"
    tags = [t for t in (raw.get("tags") or []) if t]
    ordered = [book_slug]
    for t in tags:
        if t not in ordered and not str(t).startswith("page-"):
            ordered.append(str(t))
    if "book" not in ordered:
        ordered.append("book")
    ordered.append(f"part-{part_no}")
    raw["tags"] = ordered

    topic_fallback = f"Часть {part_no}"
    min_q = max(5, min(8, questions_n // 2))
    try:
        return _sanitize_test_doc(raw, topic_fallback=topic_fallback, min_questions=min_q)
    except (ValidationError, OllamaError) as first_exc:
        # one repair call: the model fixes the same JSON
        logger.warning("sanitize/validate failed part %s: %s — repair", part_no, first_exc)
        repair_user = f"""Исправь JSON теста. Верни ТОЛЬКО валидный JSON того же теста.
Ошибки: {first_exc}
Требования: у каждого вопроса есть options (объект 2–8 ключей), correct (массив ключей из options),
explanation (непусто). single/true_false → correct длина 1. true_false options={{"A":"Верно","B":"Неверно"}}.
Число вопросов желательно ≈{questions_n}, минимум {min_q}.

Было:
{json.dumps(raw, ensure_ascii=False)[:12000]}
"""
        fixed = await ollama_chat_json(SYSTEM_PROMPT, repair_user, temperature=0.1)
        if isinstance(fixed, list):
            fixed = fixed[0]
        if not isinstance(fixed, dict):
            raise OllamaError(f"validation failed: {first_exc}") from first_exc
        fixed.setdefault("schema_version", 1)
        fixed["external_id"] = raw["external_id"]
        fixed["tags"] = raw["tags"]
        if not str(fixed.get("title") or "").strip():
            fixed["title"] = raw["title"]
        try:
            return _sanitize_test_doc(fixed, topic_fallback=topic_fallback, min_questions=min_q)
        except (ValidationError, OllamaError) as exc:
            raise OllamaError(f"validation failed after repair: {exc}") from exc


async def run_book_job(db: Session, job_id: int, notify: ProgressCb | None = None) -> None:
    settings = get_settings()
    job = db.get(BookJob, job_id)
    if not job:
        return

    if job.status == "cancelled" or is_cancelled(job_id):
        clear_cancel(job_id)
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        append_job_log(job_id, "Задача отменена до старта")
        return

    clear_cancel(job_id)
    clear_job_log(job_id)

    async def _notify(msg: str) -> None:
        logger.info("[job %s] %s", job_id, msg)
        append_job_log(job_id, msg)
        if notify:
            res = notify(msg)
            if hasattr(res, "__await__"):
                await res  # type: ignore[misc]

    def _check_cancel() -> None:
        db.refresh(job)
        if is_cancelled(job_id) or job.status in ("cancelling", "cancelled"):
            raise BookJobCancelled("остановлено пользователем")

    try:
        pdf_path = Path(job.pdf_path)
        size_mb = pdf_path.stat().st_size / (1024 * 1024) if pdf_path.exists() else 0
        await _notify(f"PDF принят: {pdf_path.name} ({size_mb:.2f} МБ)")
        _check_cancel()

        job.status = "extracting"
        job.error = None
        db.commit()
        await _notify("Шаг 1/3: извлечение текста из PDF (PyMuPDF)…")

        pages = extract_pdf_pages(pdf_path)
        if settings.book_max_pages and len(pages) > settings.book_max_pages:
            pages = pages[: settings.book_max_pages]
            await _notify(f"Обрезано до {settings.book_max_pages} страниц (лимит BOOK_MAX_PAGES)")

        nonempty = sum(1 for p in pages if len((p.get("text") or "").strip()) >= settings.book_min_page_chars)
        job.page_count = len(pages)
        db.commit()
        await _notify(f"Извлечено страниц: {len(pages)}, с текстом ≥{settings.book_min_page_chars} симв.: {nonempty}")

        jdir = job_dir(job.id)
        readable = pages_to_readable_markdown(job.title, pages)
        readable_path = jdir / "readable.md"
        readable_path.write_text(readable, encoding="utf-8")
        (jdir / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
        job.readable_path = str(readable_path)
        db.commit()
        await _notify(f"Шаг 2/3: readable.md сохранён ({len(readable)} символов)")

        await _notify(f"Проверка Ollama ({settings.ollama_base_url}, model={settings.ollama_model})…")
        ping = await ollama_ping()
        if not ping.get("ok"):
            raise OllamaError(
                f"Ollama недоступна: {ping.get('error')} @ {ping.get('base_url')}. "
                f"Из Docker нельзя ходить на 127.0.0.1 хоста — укажи IP хоста или host.docker.internal"
            )
        models = ping.get("models") or []
        await _notify(f"Ollama OK. Модели: {', '.join(models[:8]) or '—'}")

        job.status = "generating"
        db.commit()

        examples_root = Path(settings.examples_dir)
        section_dir = examples_root / job.slug
        section_dir.mkdir(parents=True, exist_ok=True)

        qn = max(5, min(25, int(getattr(settings, "book_questions_per_test", None) or settings.book_questions_per_page or 15)))
        pages_per_chunk = max(1, min(20, int(getattr(settings, "book_pages_per_chunk", 5) or 5)))
        min_chars = settings.book_min_page_chars

        usable = [p for p in pages if len((p.get("text") or "").strip()) >= min_chars]
        skipped = len(pages) - len(usable)
        chunks = _chunk_pages(usable, pages_per_chunk)
        await _notify(
            f"Шаг 3/3: генерация в раздел examples/{job.slug}/ — "
            f"{len(chunks)} тест(ов) ≈{qn} вопросов, по {pages_per_chunk} стр. на тест"
            + (f" (пропуск пустых: {skipped})" if skipped else "")
        )

        generated = 0
        failed_parts = 0
        last_err = ""
        pages_covered = 0

        for part_no, chunk in enumerate(chunks, start=1):
            _check_cancel()
            pages_covered += len(chunk)
            # progress by pages covered (UI uses pages_done / page_count)
            job.pages_done = min(job.page_count or pages_covered, pages_covered + skipped)
            db.commit()

            page_range = f"{chunk[0]['page']}-{chunk[-1]['page']}"
            await _notify(f"часть {part_no}/{len(chunks)} (стр. {page_range}): запрос к модели…")
            _check_cancel()
            try:
                doc = await generate_test_for_chunk(
                    book_title=job.title,
                    book_slug=job.slug,
                    part_no=part_no,
                    pages=chunk,
                    questions_n=qn,
                )
                topic = slugify(
                    str((doc.get("questions") or [{}])[0].get("topic") or f"part-{part_no}")
                )
                if not topic or topic in ("book", job.slug):
                    topic = f"part-{part_no}"
                out_path = _unique_topic_path(section_dir, topic, part_no)
                doc["external_id"] = f"{job.slug}/{out_path.stem}"
                # keep book slug as first tag for folder grouping
                tags = [job.slug] + [t for t in (doc.get("tags") or []) if t != job.slug]
                doc["tags"] = tags
                out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                generated += 1
                job.tests_generated = generated
                db.commit()
                await _notify(
                    f"часть {part_no}/{len(chunks)}: ✓ {out_path.name} "
                    f"({len(doc.get('questions') or [])}q) · всего тестов {generated}"
                )
            except BookJobCancelled:
                raise
            except Exception as exc:
                failed_parts += 1
                last_err = str(exc)
                logger.exception("part %s failed", part_no)
                await _notify(f"часть {part_no}/{len(chunks)}: ✗ {exc}")
                # do not abort the whole book on a run of proxy drops — keep going
                if generated == 0 and failed_parts >= 8:
                    raise OllamaError(f"Остановка: слишком много ошибок Ollama подряд ({last_err})")

        job.pages_done = job.page_count or pages_covered
        job.tests_generated = generated
        job.finished_at = datetime.now(timezone.utc)
        if generated == 0:
            job.status = "failed"
            job.error = (
                last_err
                or f"Не создано ни одного теста (пропусков страниц {skipped}, ошибок частей {failed_parts}). Проверь Ollama и текст PDF."
            )[:2000]
            db.commit()
            await _notify(f"ИТОГ: FAILED — 0 тестов. {job.error}")
        else:
            job.status = "done"
            if failed_parts:
                job.error = f"Частично: ошибок частей {failed_parts}, успешно {generated}"
            db.commit()
            await _notify(
                f"ИТОГ: OK — раздел examples/{job.slug}/ · тестов {generated} "
                f"(~{qn}q), пропуск стр. {skipped}, ошибок {failed_parts}. Runner подхватит JSON."
            )
    except BookJobCancelled as exc:
        job = db.get(BookJob, job_id)
        if job:
            job.status = "cancelled"
            job.error = str(exc)[:500]
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        clear_cancel(job_id)
        await _notify(f"ИТОГ: CANCELLED — {exc}")
    except Exception as exc:
        logger.exception("book job %s failed", job_id)
        job = db.get(BookJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)[:2000]
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        clear_cancel(job_id)
        await _notify(f"ИТОГ: FAILED — {exc}")
    else:
        clear_cancel(job_id)
