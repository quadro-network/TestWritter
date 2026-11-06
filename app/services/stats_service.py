from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Answer, Attempt, Question, Test
from app.schemas import StatsOut, TopicBreakdown
from app.services.attempt_service import get_mistake_question_ids


def compute_stats(db: Session) -> StatsOut:
    tests = db.scalars(select(Test).options(selectinload(Test.questions))).all()
    test_rows = []
    for t in tests:
        finished = db.scalars(
            select(Attempt)
            .where(Attempt.test_id == t.id, Attempt.status == "finished")
            .order_by(desc(Attempt.finished_at))
        ).all()
        best = max((a.score_percent or 0 for a in finished), default=None)
        last = finished[0].score_percent if finished else None
        test_rows.append(
            {
                "id": t.id,
                "title": t.title,
                "tags": t.tags or [],
                "question_count": len(t.questions),
                "attempts": len(finished),
                "best_percent": best,
                "last_percent": last,
            }
        )

    # topic accuracy from all answers
    answers = db.scalars(select(Answer).options(selectinload(Answer.question))).all()
    topic_map: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    q_stats: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # correct, total
    for a in answers:
        topic = (a.question.topic if a.question else None) or "без темы"
        topic_map[topic][1] += 1
        q_stats[a.question_id][1] += 1
        if a.is_correct:
            topic_map[topic][0] += 1
            q_stats[a.question_id][0] += 1

    topics = [
        TopicBreakdown(
            topic=t,
            correct=v[0],
            total=v[1],
            percent=round(100.0 * v[0] / v[1], 1) if v[1] else 0.0,
        )
        for t, v in sorted(topic_map.items(), key=lambda x: x[1][1], reverse=True)
    ]

    problematic = []
    for qid, (ok, total) in q_stats.items():
        if total < 1:
            continue
        pct = 100.0 * ok / total
        q = db.get(Question, qid)
        if not q:
            continue
        problematic.append(
            {
                "question_id": qid,
                "question": q.question[:200],
                "topic": q.topic,
                "test_id": q.test_id,
                "correct": ok,
                "total": total,
                "percent": round(pct, 1),
            }
        )
    problematic.sort(key=lambda x: (x["percent"], -x["total"]))
    problematic = problematic[:20]

    recent = db.scalars(
        select(Attempt).where(Attempt.status == "finished").order_by(desc(Attempt.finished_at)).limit(20)
    ).all()
    recent_attempts = [
        {
            "id": a.id,
            "test_id": a.test_id,
            "mode": a.mode,
            "score_percent": a.score_percent,
            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
        }
        for a in recent
    ]

    return StatsOut(
        tests=test_rows,
        topics=topics,
        problematic_questions=problematic,
        recent_attempts=recent_attempts,
    )


def topic_stats_only(db: Session) -> list[TopicBreakdown]:
    return compute_stats(db).topics


def list_mistake_questions(db: Session, test_id: int | None = None) -> list[dict]:
    ids = get_mistake_question_ids(db, test_id=test_id)
    out = []
    for qid in ids:
        q = db.get(Question, qid)
        if not q:
            continue
        out.append(
            {
                "id": q.id,
                "test_id": q.test_id,
                "topic": q.topic,
                "difficulty": q.difficulty,
                "type": q.qtype,
                "question": q.question,
                "has_code": bool(q.code_content),
            }
        )
    return out
