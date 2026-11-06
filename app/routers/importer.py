from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import require_import_token
from app.db import get_db
from app.schemas import ImportResult
from app.services.examples_store import save_docs_to_examples
from app.services.import_service import format_validation_error, import_many

logger = logging.getLogger("importer")

router = APIRouter(prefix="/import", tags=["import"], dependencies=[Depends(require_import_token)])


def _do_import(db: Session, payload: Any, *, persist: bool = True) -> dict:
    results = import_many(db, payload)
    saved: list[str] = []
    if persist:
        try:
            saved = save_docs_to_examples(payload)
        except Exception:
            logger.exception("Failed to persist examples to disk")
    return {"imported": results, "saved_to": saved}


@router.post("")
async def import_json(
    payload: dict | list = Body(...),
    persist: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return _do_import(db, payload, persist=bool(persist))
    except ValidationError as exc:
        raise HTTPException(422, format_validation_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid JSON: {exc}") from exc


@router.post("/file")
async def import_files(
    files: list[UploadFile] = File(...),
    persist: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    imported: list[ImportResult] = []
    saved_to: list[str] = []
    errors: list[dict] = []
    for f in files:
        name = f.filename or "upload.json"
        if not name.lower().endswith(".json"):
            errors.append({"file": name, "error": "only .json allowed"})
            continue
        try:
            raw = (await f.read()).decode("utf-8")
            data = json.loads(raw)
            out = _do_import(db, data, persist=bool(persist))
            imported.extend(out["imported"])
            saved_to.extend(out.get("saved_to") or [])
        except Exception as exc:
            errors.append({"file": name, "error": str(exc)})
    return {"imported": imported, "saved_to": saved_to, "errors": errors}
