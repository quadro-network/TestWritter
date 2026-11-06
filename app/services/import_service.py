from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question, Test
from app.schemas import ImportResult, TestIn


def format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = err.get("msg", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def normalize_for_hash(data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if k != "external_id"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(normalize_for_hash(data).encode("utf-8")).hexdigest()


def parse_test_payload(raw: Any) -> TestIn:
    if isinstance(raw, str):
        raw = json.loads(raw)
    return TestIn.model_validate(raw)


def _replace_questions(db: Session, test: Test, payload: TestIn) -> None:
    test.questions.clear()
    db.flush()
    for idx, q in enumerate(payload.questions):
        test.questions.append(
            Question(
                sort_order=idx,
                qtype=q.type,
                topic=q.topic,
                difficulty=q.difficulty,
                question=q.question,
                code_language=q.code.language if q.code else None,
                code_content=q.code.content if q.code else None,
                options=q.options,
                correct=list(q.correct),
                explanation=q.explanation,
                option_explanations=q.option_explanations or {},
            )
        )


def import_one(db: Session, raw: Any) -> ImportResult:
    try:
        payload = parse_test_payload(raw)
    except ValidationError as exc:
        raise ValueError(format_validation_error(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    data = payload.model_dump(mode="json")
    digest = content_hash(data)

    existing: Test | None = None
    if payload.external_id:
        existing = db.scalar(select(Test).where(Test.external_id == payload.external_id))
    if existing is None:
        existing = db.scalar(select(Test).where(Test.content_hash == digest))

    if existing:
        existing.title = payload.title
        existing.description = payload.description
        existing.tags = list(payload.tags or [])
        existing.content_hash = digest
        if payload.external_id:
            existing.external_id = payload.external_id
        _replace_questions(db, existing, payload)
        db.commit()
        db.refresh(existing)
        return ImportResult(
            id=existing.id,
            title=existing.title,
            question_count=len(existing.questions),
            created=False,
            external_id=existing.external_id,
        )

    test = Test(
        external_id=payload.external_id,
        content_hash=digest,
        title=payload.title,
        description=payload.description,
        tags=list(payload.tags or []),
    )
    db.add(test)
    db.flush()
    _replace_questions(db, test, payload)
    db.commit()
    db.refresh(test)
    return ImportResult(
        id=test.id,
        title=test.title,
        question_count=len(test.questions),
        created=True,
        external_id=test.external_id,
    )


def import_many(db: Session, raw: Any) -> list[ImportResult]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, list):
        return [import_one(db, item) for item in raw]
    return [import_one(db, raw)]


def test_to_export(test: Test) -> dict[str, Any]:
    questions = []
    for q in sorted(test.questions, key=lambda x: x.sort_order):
        item: dict[str, Any] = {
            "type": q.qtype,
            "topic": q.topic,
            "difficulty": q.difficulty,
            "question": q.question,
            "options": q.options,
            "correct": q.correct,
            "explanation": q.explanation,
            "option_explanations": q.option_explanations or {},
        }
        if q.code_language and q.code_content:
            item["code"] = {"language": q.code_language, "content": q.code_content}
        questions.append(item)
    return {
        "schema_version": 1,
        "external_id": test.external_id,
        "title": test.title,
        "description": test.description,
        "tags": test.tags or [],
        "questions": questions,
    }
