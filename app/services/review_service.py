from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models import Attempt, Test
from app.services.attempt_service import _latest_answers_subquery


def build_review_bundle(
    db: Session,
    test_ids: list[int] | None = None,
    *,
    only_mistakes: bool = True,
    limit: int | None = 80,
) -> dict:
    """Bundle of results for AI review prompt (includes correct answers)."""
    stmt = select(Test).options(selectinload(Test.questions)).order_by(Test.id)
    if test_ids:
        stmt = stmt.where(Test.id.in_(test_ids))
    tests = list(db.scalars(stmt).all())
    latest = _latest_answers_subquery(db)

    items: list[dict] = []
    topic_wrong: dict[str, int] = defaultdict(int)
    topic_total: dict[str, int] = defaultdict(int)
    all_mistakes: list[dict] = []

    for t in tests:
        finished = db.scalars(
            select(Attempt)
            .where(Attempt.test_id == t.id, Attempt.status == "finished")
            .order_by(desc(Attempt.finished_at))
        ).all()

        best = max((a.score_percent or 0.0) for a in finished) if finished else None
        last = finished[0].score_percent if finished else None

        mistakes: list[dict] = []
        for q in sorted(t.questions, key=lambda x: x.sort_order):
            ans = latest.get(q.id)
            if ans is None:
                continue
            topic = q.topic or "без темы"
            topic_total[topic] += 1
            if not ans.is_correct:
                topic_wrong[topic] += 1

            if only_mistakes and ans.is_correct:
                continue

            row = {
                "question_id": q.id,
                "test_id": t.id,
                "test_title": t.title,
                "type": q.qtype,
                "topic": q.topic,
                "difficulty": q.difficulty,
                "question": q.question,
                "code": (
                    {"language": q.code_language, "content": q.code_content}
                    if q.code_language and q.code_content
                    else None
                ),
                "options": dict(q.options or {}),
                "selected": list(ans.selected or []),
                "correct": list(q.correct or []),
                "is_correct": bool(ans.is_correct),
                "explanation": q.explanation,
                "option_explanations": dict(q.option_explanations or {}),
            }
            mistakes.append(row)
            if not ans.is_correct:
                all_mistakes.append(row)

        if limit is not None:
            mistakes = mistakes[:limit]

        items.append(
            {
                "test_id": t.id,
                "title": t.title,
                "tags": list(t.tags or []),
                "question_count": len(t.questions),
                "attempts": len(finished),
                "best_percent": best,
                "last_percent": last,
                "mistakes": mistakes,
                "mistake_count": sum(1 for m in mistakes if not m["is_correct"]),
            }
        )

    if limit is not None:
        all_mistakes = all_mistakes[:limit]

    topics = [
        {
            "topic": topic,
            "wrong": topic_wrong[topic],
            "answered": topic_total[topic],
            "percent_correct": round(
                100.0 * (topic_total[topic] - topic_wrong[topic]) / topic_total[topic], 1
            )
            if topic_total[topic]
            else 0.0,
        }
        for topic in sorted(topic_total.keys(), key=lambda x: (-topic_wrong[x], x))
    ]

    return {
        "tests": items,
        "topics": topics,
        "mistakes": all_mistakes,
        "total_mistakes": len(all_mistakes),
    }
