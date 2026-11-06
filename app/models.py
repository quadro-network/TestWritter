from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    questions: Mapped[list[Question]] = relationship(
        back_populates="test", cascade="all, delete-orphan", order_by="Question.sort_order"
    )
    attempts: Mapped[list[Attempt]] = relationship(back_populates="test", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qtype: Mapped[str] = mapped_column("type", String(32), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    code_language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    code_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correct: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    option_explanations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    test: Mapped[Test] = relationship(back_populates="questions")
    answers: Mapped[list[Answer]] = relationship(back_populates="question", cascade="all, delete-orphan")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full")
    tag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    shuffle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    score_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    test: Mapped[Optional[Test]] = relationship(back_populates="attempts")
    items: Mapped[list[AttemptQuestion]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", order_by="AttemptQuestion.sort_order"
    )
    answers: Mapped[list[Answer]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class AttemptQuestion(Base):
    __tablename__ = "attempt_questions"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    attempt: Mapped[Attempt] = relationship(back_populates="items")
    question: Mapped[Question] = relationship()


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    selected: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship(back_populates="answers")


class ReminderSetting(Base):
    __tablename__ = "reminder_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BookJob(Base):
    __tablename__ = "book_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    # queued | extracting | generating | done | failed
    pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    readable_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tests_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

