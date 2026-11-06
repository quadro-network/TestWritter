from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.schemas import TestIn
from app.services.import_service import content_hash, format_validation_error, import_one

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "k8s_sample.json"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_sample_validates():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    parsed = TestIn.model_validate(data)
    assert parsed.title
    assert len(parsed.questions) >= 8


def test_rejects_unknown_correct_key():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data["questions"][0]["correct"] = ["Z"]
    with pytest.raises(ValidationError) as ei:
        TestIn.model_validate(data)
    msg = format_validation_error(ei.value)
    assert "questions.0.correct" in msg or "correct" in msg


def test_single_requires_one_correct():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data["questions"][0]["correct"] = ["A", "B"]
    with pytest.raises(ValidationError):
        TestIn.model_validate(data)


def test_import_idempotent_by_external_id(db):
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    r1 = import_one(db, data)
    data["title"] = "Kubernetes: основы (обновлено)"
    data["questions"] = data["questions"][:3]
    r2 = import_one(db, data)
    assert r1.id == r2.id
    assert r2.created is False
    assert r2.question_count == 3
    assert r2.title.startswith("Kubernetes")


def test_import_idempotent_by_hash(db):
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data.pop("external_id", None)
    r1 = import_one(db, data)
    r2 = import_one(db, data)
    assert r1.id == r2.id
    assert r2.created is False
    assert content_hash(TestIn.model_validate(data).model_dump(mode="json"))
