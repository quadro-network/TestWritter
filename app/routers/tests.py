from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_import_token
from app.db import get_db
from app.models import Attempt, Question, Test
from app.schemas import CodeBlock, QuestionFull, TestIn, TestListItem, TestOut
from app.services.import_service import content_hash, import_one, test_to_export

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(require_import_token)])


def _best_last(db: Session, test_id: int) -> tuple[float | None, float | None]:
    finished = db.scalars(
        select(Attempt)
        .where(Attempt.test_id == test_id, Attempt.status == "finished")
        .order_by(desc(Attempt.finished_at))
    ).all()
    if not finished:
        return None, None
    best = max((a.score_percent or 0.0) for a in finished)
    last = finished[0].score_percent
    return best, last


def _to_full(test: Test) -> TestOut:
    questions = []
    for q in sorted(test.questions, key=lambda x: x.sort_order):
        code = None
        if q.code_language and q.code_content:
            code = CodeBlock(language=q.code_language, content=q.code_content)
        questions.append(
            QuestionFull(
                id=q.id,
                type=q.qtype,  # type: ignore[arg-type]
                topic=q.topic,
                difficulty=q.difficulty,
                question=q.question,
                code=code,
                options=dict(q.options or {}),
                sort_order=q.sort_order,
                correct=list(q.correct),
                explanation=q.explanation,
                option_explanations=dict(q.option_explanations or {}),
            )
        )
    return TestOut(
        id=test.id,
        external_id=test.external_id,
        title=test.title,
        description=test.description,
        tags=list(test.tags or []),
        questions=questions,
        created_at=test.created_at,
        updated_at=test.updated_at,
    )


@router.get("")
def list_tests(
    tag: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    tests = db.scalars(
        select(Test).options(selectinload(Test.questions)).order_by(desc(Test.updated_at))
    ).all()
    items: list[TestListItem] = []
    for t in tests:
        tags = list(t.tags or [])
        if tag and tag not in tags:
            continue
        if q and q.lower() not in t.title.lower() and q.lower() not in (t.description or "").lower():
            continue
        best, last = _best_last(db, t.id)
        items.append(
            TestListItem(
                id=t.id,
                external_id=t.external_id,
                title=t.title,
                description=t.description,
                tags=tags,
                question_count=len(t.questions),
                best_percent=best,
                last_percent=last,
                updated_at=t.updated_at,
            )
        )
    total = len(items)
    start = (page - 1) * size
    page_items = items[start : start + size]
    return {"items": page_items, "total": total, "page": page, "size": size}


@router.get("/{test_id}", response_model=TestOut)
def get_test(test_id: int, db: Session = Depends(get_db)) -> TestOut:
    test = db.scalar(select(Test).where(Test.id == test_id).options(selectinload(Test.questions)))
    if not test:
        raise HTTPException(404, "test not found")
    return _to_full(test)


@router.post("", response_model=TestOut)
def create_test(body: TestIn, db: Session = Depends(get_db)) -> TestOut:
    result = import_one(db, body.model_dump(mode="json"))
    test = db.scalar(select(Test).where(Test.id == result.id).options(selectinload(Test.questions)))
    assert test
    return _to_full(test)


@router.put("/{test_id}", response_model=TestOut)
def update_test(test_id: int, body: TestIn, db: Session = Depends(get_db)) -> TestOut:
    test = db.scalar(select(Test).where(Test.id == test_id).options(selectinload(Test.questions)))
    if not test:
        raise HTTPException(404, "test not found")
    data = body.model_dump(mode="json")
    # force update of this row via external_id or temporary external
    if body.external_id:
        data["external_id"] = body.external_id
    elif test.external_id:
        data["external_id"] = test.external_id
    else:
        data["external_id"] = f"test-{test_id}"
        test.external_id = data["external_id"]
        db.commit()
    result = import_one(db, data)
    test = db.scalar(select(Test).where(Test.id == result.id).options(selectinload(Test.questions)))
    assert test
    return _to_full(test)


@router.delete("/{test_id}")
def delete_test(test_id: int, db: Session = Depends(get_db)) -> dict:
    test = db.get(Test, test_id)
    if not test:
        raise HTTPException(404, "test not found")
    db.delete(test)
    db.commit()
    return {"ok": True}


@router.get("/{test_id}/export")
def export_test(test_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    test = db.scalar(select(Test).where(Test.id == test_id).options(selectinload(Test.questions)))
    if not test:
        raise HTTPException(404, "test not found")
    payload = test_to_export(test)
    filename = f"test_{test_id}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
