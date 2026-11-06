from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


QuestionType = Literal["single", "multiple", "true_false"]
AttemptMode = Literal["full", "mistakes", "random"]


class CodeBlock(BaseModel):
    language: str = Field(min_length=1)
    content: str = Field(min_length=1)


class QuestionIn(BaseModel):
    type: QuestionType
    topic: Optional[str] = None
    difficulty: int = Field(default=1, ge=1, le=5)
    question: str = Field(min_length=1)
    code: Optional[CodeBlock] = None
    options: dict[str, str]
    correct: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    option_explanations: dict[str, str] = Field(default_factory=dict)

    @field_validator("question", "explanation")
    @classmethod
    def non_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: dict[str, str]) -> dict[str, str]:
        if not (2 <= len(v) <= 8):
            raise ValueError("options must contain 2–8 items")
        keys = list(v.keys())
        if len(keys) != len(set(keys)):
            raise ValueError("option keys must be unique")
        for k, text in v.items():
            if not str(text).strip():
                raise ValueError(f"option {k} text must not be empty")
        return v

    @model_validator(mode="after")
    def validate_correct(self) -> QuestionIn:
        opt_keys = set(self.options.keys())
        for key in self.correct:
            if key not in opt_keys:
                raise ValueError(f"correct key '{key}' is not among options")
        if self.type in ("single", "true_false") and len(self.correct) != 1:
            raise ValueError(f"for type={self.type} correct must contain exactly 1 value")
        if self.type == "multiple" and len(self.correct) < 1:
            raise ValueError("for type=multiple correct must contain at least 1 value")
        if self.type == "true_false" and set(self.options.keys()) - {"true", "false", "True", "False", "A", "B"}:
            # allow flexible true/false option keys; no hard fail
            pass
        bad_opt_expl = [k for k in self.option_explanations if k not in opt_keys]
        if bad_opt_expl:
            raise ValueError(f"option_explanations keys not in options: {bad_opt_expl}")
        return self


class QuizDocument(BaseModel):
    """Incoming test JSON (schema_version 1)."""

    schema_version: Literal[1] = 1
    external_id: Optional[str] = None
    title: str = Field(min_length=1)
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    questions: list[QuestionIn] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def title_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


# Alias used across routers/services
TestIn = QuizDocument


class QuestionPublic(BaseModel):
    id: int
    type: QuestionType
    topic: Optional[str] = None
    difficulty: int
    question: str
    code: Optional[CodeBlock] = None
    options: dict[str, str]
    sort_order: int = 0


class QuestionFull(QuestionPublic):
    correct: list[str]
    explanation: str
    option_explanations: dict[str, str] = Field(default_factory=dict)


class TestListItem(BaseModel):
    id: int
    external_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    tags: list[str]
    question_count: int
    best_percent: Optional[float] = None
    last_percent: Optional[float] = None
    updated_at: Optional[datetime] = None


class TestOut(BaseModel):
    id: int
    schema_version: int = 1
    external_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    tags: list[str]
    questions: list[QuestionFull]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TestExport(BaseModel):
    schema_version: Literal[1] = 1
    external_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    questions: list[QuestionIn]


class AttemptCreate(BaseModel):
    test_id: Optional[int] = None
    mode: AttemptMode = "full"
    tag: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=200)
    shuffle: bool = False
    telegram_user_id: Optional[str] = None


class AttemptCreated(BaseModel):
    attempt_id: int
    mode: AttemptMode
    total: int
    questions: list[QuestionPublic]


class AnswerIn(BaseModel):
    question_id: int
    selected: list[str]


class AnswerOut(BaseModel):
    is_correct: bool
    correct: list[str]
    explanation: str
    option_explanations: dict[str, str] = Field(default_factory=dict)
    already_answered: bool = False


class TopicBreakdown(BaseModel):
    topic: str
    total: int
    correct: int
    percent: float


class MistakeItem(BaseModel):
    question_id: int
    question: str
    topic: Optional[str] = None
    selected: list[str]
    correct: list[str]
    explanation: str
    options: dict[str, str]


class AttemptFinishOut(BaseModel):
    attempt_id: int
    score_percent: float
    correct_count: int
    total: int
    by_topic: list[TopicBreakdown]
    mistakes: list[MistakeItem]


class AttemptState(BaseModel):
    attempt_id: int
    status: str
    mode: AttemptMode
    test_id: Optional[int] = None
    total: int
    answered_count: int
    score_so_far: Optional[float] = None
    questions: list[QuestionPublic]
    answers: dict[str, Any] = Field(default_factory=dict)


class ImportResult(BaseModel):
    id: int
    title: str
    question_count: int
    created: bool
    external_id: Optional[str] = None


class StatsOut(BaseModel):
    tests: list[dict[str, Any]]
    topics: list[TopicBreakdown]
    problematic_questions: list[dict[str, Any]]
    recent_attempts: list[dict[str, Any]]


class HealthOut(BaseModel):
    status: str
    database: bool
