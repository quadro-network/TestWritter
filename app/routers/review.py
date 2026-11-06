from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_import_token
from app.db import get_db
from app.services.review_service import build_review_bundle

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(require_import_token)])


class ReviewBundleIn(BaseModel):
    test_ids: list[int] = Field(default_factory=list)
    only_mistakes: bool = True
    limit: int | None = Field(default=80, ge=1, le=200)


@router.post("/bundle")
def review_bundle(body: ReviewBundleIn, db: Session = Depends(get_db)) -> dict:
    ids = body.test_ids or None
    return build_review_bundle(
        db,
        ids,
        only_mistakes=body.only_mistakes,
        limit=body.limit,
    )
