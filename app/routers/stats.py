from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_import_token
from app.db import get_db
from app.schemas import StatsOut, TopicBreakdown
from app.services import stats_service

router = APIRouter(tags=["stats"], dependencies=[Depends(require_import_token)])


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    return stats_service.compute_stats(db)


@router.get("/stats/topics", response_model=list[TopicBreakdown])
def stats_topics(db: Session = Depends(get_db)) -> list[TopicBreakdown]:
    return stats_service.topic_stats_only(db)


@router.get("/questions/mistakes")
def mistakes(
    test_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": stats_service.list_mistake_questions(db, test_id=test_id)}
