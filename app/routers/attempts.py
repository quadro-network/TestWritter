from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_import_token
from app.db import get_db
from app.schemas import AnswerIn, AnswerOut, AttemptCreate, AttemptCreated, AttemptFinishOut, AttemptState
from app.services import attempt_service

router = APIRouter(prefix="/attempts", tags=["attempts"], dependencies=[Depends(require_import_token)])


@router.get("")
def list_attempts(
    active: int | None = Query(default=None),
    telegram_user_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    if active == 1:
        items = attempt_service.list_active_attempts(db, telegram_user_id=telegram_user_id)
        return {"items": items}
    raise HTTPException(400, "use ?active=1")


@router.post("", response_model=AttemptCreated)
def create_attempt(body: AttemptCreate, db: Session = Depends(get_db)) -> AttemptCreated:
    try:
        return attempt_service.create_attempt(
            db,
            test_id=body.test_id,
            mode=body.mode,
            tag=body.tag,
            limit=body.limit,
            shuffle=body.shuffle,
            telegram_user_id=body.telegram_user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{attempt_id}", response_model=AttemptState)
def get_attempt(attempt_id: int, db: Session = Depends(get_db)) -> AttemptState:
    try:
        return attempt_service.get_attempt(db, attempt_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{attempt_id}/answer", response_model=AnswerOut)
def answer(attempt_id: int, body: AnswerIn, db: Session = Depends(get_db)) -> AnswerOut:
    try:
        return attempt_service.submit_answer(db, attempt_id, body.question_id, body.selected)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{attempt_id}/finish", response_model=AttemptFinishOut)
def finish(attempt_id: int, db: Session = Depends(get_db)) -> AttemptFinishOut:
    try:
        return attempt_service.finish_attempt(db, attempt_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
