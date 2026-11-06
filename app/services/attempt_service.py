from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Answer, Attempt, AttemptQuestion, Question, Test
from app.schemas import (
    AnswerOut,
    AttemptCreated,
    AttemptFinishOut,
    AttemptState,
    CodeBlock,
    MistakeItem,
    QuestionPublic,
    TopicBreakdown,
)


def _question_public(q: Question, sort_order: int = 0) -> QuestionPublic:
    code = None
    if q.code_language and q.code_content:
        code = CodeBlock(language=q.code_language, content=q.code_content)
    return QuestionPublic(
        id=q.id,
        type=q.qtype,  # type: ignore[arg-type]
        topic=q.topic,
        difficulty=q.difficulty,
        question=q.question,
        code=code,
        options=dict(q.options or {}),
        sort_order=sort_order,
    )


def _latest_answers_subquery(db: Session) -> dict[int, Answer]:
    """Map question_id → latest Answer across finished/active attempts."""
    answers = db.scalars(select(Answer).order_by(desc(Answer.answered_at), desc(Answer.id))).all()
    latest: dict[int, Answer] = {}
    for a in answers:
        if a.question_id not in latest:
            latest[a.question_id] = a
    return latest


def get_mistake_question_ids(db: Session, test_id: Optional[int] = None) -> list[int]:
    latest = _latest_answers_subquery(db)
    ids: list[int] = []
    for qid, ans in latest.items():
        if not ans.is_correct:
            if test_id is not None:
                q = db.get(Question, qid)
                if not q or q.test_id != test_id:
                    continue
            ids.append(qid)
    return ids


def select_questions(
    db: Session,
    *,
    test_id: Optional[int],
    mode: str,
    tag: Optional[str],
    limit: Optional[int],
    shuffle: bool,
) -> list[Question]:
    stmt: Select[tuple[Question]] = (
        select(Question).join(Test).options(joinedload(Question.test))
    )

    if mode == "mistakes":
        mistake_ids = get_mistake_question_ids(db, test_id=test_id)
        if not mistake_ids:
            return []
        stmt = stmt.where(Question.id.in_(mistake_ids))
    elif test_id is not None:
        stmt = stmt.where(Question.test_id == test_id)

    questions = list(db.scalars(stmt.order_by(Question.test_id, Question.sort_order)).unique().all())
    if tag:
        questions = [q for q in questions if tag in (q.test.tags or [])]

    if mode == "random" or shuffle:
        random.shuffle(questions)
    if limit:
        questions = questions[:limit]
    return questions


def create_attempt(
    db: Session,
    *,
    test_id: Optional[int],
    mode: str,
    tag: Optional[str],
    limit: Optional[int],
    shuffle: bool,
    telegram_user_id: Optional[str] = None,
) -> AttemptCreated:
    if mode == "full" and test_id is None and not tag:
        raise ValueError("test_id or tag required for full mode")
    if mode == "random" and limit is None:
        limit = 10

    questions = select_questions(
        db, test_id=test_id, mode=mode, tag=tag, limit=limit, shuffle=shuffle or mode == "random"
    )
    if not questions:
        raise ValueError("no questions matched the criteria")

    attempt = Attempt(
        test_id=test_id,
        mode=mode,
        tag=tag,
        shuffle=shuffle or mode == "random",
        status="active",
        telegram_user_id=telegram_user_id,
    )
    db.add(attempt)
    db.flush()
    public: list[QuestionPublic] = []
    for idx, q in enumerate(questions):
        db.add(AttemptQuestion(attempt_id=attempt.id, question_id=q.id, sort_order=idx))
        public.append(_question_public(q, sort_order=idx))
    db.commit()
    return AttemptCreated(attempt_id=attempt.id, mode=mode, total=len(public), questions=public)  # type: ignore[arg-type]


def get_attempt(db: Session, attempt_id: int) -> AttemptState:
    attempt = db.scalar(
        select(Attempt)
        .where(Attempt.id == attempt_id)
        .options(
            selectinload(Attempt.items).selectinload(AttemptQuestion.question),
            selectinload(Attempt.answers),
        )
    )
    if not attempt:
        raise LookupError("attempt not found")

    answered = {a.question_id: a for a in attempt.answers}
    questions = [
        _question_public(item.question, sort_order=item.sort_order)
        for item in sorted(attempt.items, key=lambda x: x.sort_order)
    ]
    answers_out = {
        str(qid): {"selected": a.selected, "is_correct": a.is_correct}
        for qid, a in answered.items()
    }
    correct_n = sum(1 for a in answered.values() if a.is_correct)
    score = round(100.0 * correct_n / len(questions), 1) if answered and questions else None
    return AttemptState(
        attempt_id=attempt.id,
        status=attempt.status,
        mode=attempt.mode,  # type: ignore[arg-type]
        test_id=attempt.test_id,
        total=len(questions),
        answered_count=len(answered),
        score_so_far=score,
        questions=questions,
        answers=answers_out,
    )


def list_active_attempts(db: Session, telegram_user_id: Optional[str] = None) -> list[AttemptState]:
    stmt = select(Attempt).where(Attempt.status == "active").order_by(desc(Attempt.created_at))
    if telegram_user_id:
        stmt = stmt.where(Attempt.telegram_user_id == telegram_user_id)
    attempts = db.scalars(stmt).all()
    return [get_attempt(db, a.id) for a in attempts]


def submit_answer(db: Session, attempt_id: int, question_id: int, selected: list[str]) -> AnswerOut:
    attempt = db.get(Attempt, attempt_id)
    if not attempt:
        raise LookupError("attempt not found")
    if attempt.status != "active":
        raise ValueError("attempt is finished")

    link = db.scalar(
        select(AttemptQuestion).where(
            AttemptQuestion.attempt_id == attempt_id,
            AttemptQuestion.question_id == question_id,
        )
    )
    if not link:
        raise LookupError("question not in this attempt")

    existing = db.scalar(
        select(Answer).where(Answer.attempt_id == attempt_id, Answer.question_id == question_id)
    )
    q = db.get(Question, question_id)
    if not q:
        raise LookupError("question not found")

    if existing:
        return AnswerOut(
            is_correct=existing.is_correct,
            correct=list(q.correct),
            explanation=q.explanation,
            option_explanations=dict(q.option_explanations or {}),
            already_answered=True,
        )

    correct_set = set(q.correct)
    selected_set = set(selected)
    is_correct = selected_set == correct_set
    answer = Answer(
        attempt_id=attempt_id,
        question_id=question_id,
        selected=list(selected),
        is_correct=is_correct,
    )
    db.add(answer)
    db.commit()
    return AnswerOut(
        is_correct=is_correct,
        correct=list(q.correct),
        explanation=q.explanation,
        option_explanations=dict(q.option_explanations or {}),
        already_answered=False,
    )


def finish_attempt(db: Session, attempt_id: int) -> AttemptFinishOut:
    attempt = db.scalar(
        select(Attempt)
        .where(Attempt.id == attempt_id)
        .options(
            selectinload(Attempt.items).selectinload(AttemptQuestion.question),
            selectinload(Attempt.answers),
        )
    )
    if not attempt:
        raise LookupError("attempt not found")

    by_qid = {a.question_id: a for a in attempt.answers}
    total = len(attempt.items)
    correct_count = 0
    topic_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    mistakes: list[MistakeItem] = []

    for item in sorted(attempt.items, key=lambda x: x.sort_order):
        q = item.question
        topic = q.topic or "без темы"
        topic_stats[topic][1] += 1
        ans = by_qid.get(q.id)
        if ans and ans.is_correct:
            correct_count += 1
            topic_stats[topic][0] += 1
        elif ans and not ans.is_correct:
            mistakes.append(
                MistakeItem(
                    question_id=q.id,
                    question=q.question,
                    topic=q.topic,
                    selected=list(ans.selected),
                    correct=list(q.correct),
                    explanation=q.explanation,
                    options=dict(q.options or {}),
                )
            )
        elif ans is None:
            # unanswered counts as wrong for score
            mistakes.append(
                MistakeItem(
                    question_id=q.id,
                    question=q.question,
                    topic=q.topic,
                    selected=[],
                    correct=list(q.correct),
                    explanation=q.explanation,
                    options=dict(q.options or {}),
                )
            )

    percent = round(100.0 * correct_count / total, 1) if total else 0.0
    attempt.status = "finished"
    attempt.score_percent = percent
    attempt.finished_at = datetime.now(timezone.utc)
    db.commit()

    by_topic = [
        TopicBreakdown(
            topic=t,
            correct=vals[0],
            total=vals[1],
            percent=round(100.0 * vals[0] / vals[1], 1) if vals[1] else 0.0,
        )
        for t, vals in sorted(topic_stats.items())
    ]
    return AttemptFinishOut(
        attempt_id=attempt.id,
        score_percent=percent,
        correct_count=correct_count,
        total=total,
        by_topic=by_topic,
        mistakes=mistakes,
    )
