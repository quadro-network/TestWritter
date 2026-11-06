from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardMarkup

from bot import keyboards as kb


def difficulty_bar(n: int) -> str:
    d = max(1, min(5, int(n or 1)))
    filled = min(3, d)
    return "●" * filled + "○" * (3 - filled)


def format_question(attempt: dict, idx: int) -> tuple[str, InlineKeyboardMarkup, str | None]:
    q = attempt["questions"][idx]
    total = attempt["total"]
    topic = html.escape(q.get("topic") or "без темы")
    text = html.escape(q["question"])
    header = (
        f"<b>Вопрос {idx + 1}/{total}</b> · {topic} · "
        f"сложность {difficulty_bar(q.get('difficulty', 1))}\n\n{text}"
    )
    code_msg = None
    code = q.get("code")
    if code:
        lang = html.escape(code.get("language") or "text")
        content = html.escape(code.get("content") or "")
        block = f'<pre><code class="language-{lang}">{content}</code></pre>'
        candidate = header + "\n\n" + block
        if len(candidate) > 4000:
            code_msg = block
        else:
            header = candidate

    lines = [header, ""]
    keys = list((q.get("options") or {}).keys())
    for k in keys:
        lines.append(f"<b>{html.escape(k)})</b> {html.escape(q['options'][k])}")
    body = "\n".join(lines)
    if len(body) > 4000:
        body = body[:3990] + "…"

    qtype = q.get("type")
    attempt_id = attempt["attempt_id"]
    if qtype == "true_false":
        markup = kb.true_false(attempt_id, idx, keys)
    elif qtype == "multiple":
        markup = kb.multiple_options(attempt_id, idx, keys, set())
    else:
        markup = kb.single_options(attempt_id, idx, keys)
    return body, markup, code_msg


def format_feedback(q: dict, ans: dict, selected: list[str]) -> str:
    mark = "✅" if ans.get("is_correct") else "❌"
    correct = ", ".join(html.escape(x) for x in ans.get("correct") or [])
    expl = html.escape(ans.get("explanation") or "")
    parts = [
        f"{mark} {'Верно' if ans.get('is_correct') else 'Неверно'}",
        f"Правильный ответ: <b>{correct}</b>",
        f"💡 {expl}",
    ]
    opt_expl = ans.get("option_explanations") or {}
    for k in selected:
        if k not in (ans.get("correct") or []) and k in opt_expl:
            parts.append(f"· <b>{html.escape(k)}</b>: {html.escape(opt_expl[k])}")
    return "\n".join(parts)


def format_finish(result: dict) -> str:
    lines = [
        f"<b>Итог: {result['score_percent']}%</b>",
        f"{result['correct_count']} из {result['total']}",
        "",
        "<b>По темам</b>",
    ]
    for t in result.get("by_topic") or []:
        pct = int(round(t["percent"] / 10))
        bar = "█" * pct + "░" * (10 - pct)
        lines.append(f"{html.escape(t['topic'])}: {t['percent']}% {bar}")
    return "\n".join(lines)


def quiz_poll_eligible(q: dict) -> bool:
    if q.get("type") != "single":
        return False
    if q.get("code"):
        return False
    if len(q.get("question") or "") > 300:
        return False
    opts = q.get("options") or {}
    if any(len(v) > 100 for v in opts.values()):
        return False
    return True


def build_poll(q: dict) -> dict[str, Any] | None:
    if not quiz_poll_eligible(q):
        return None
    keys = list(q["options"].keys())
    options = [q["options"][k][:100] for k in keys]
    correct_key = (q.get("correct") or [None])[0]
    if correct_key not in keys:
        return None
    correct_option_id = keys.index(correct_key)
    explanation = (q.get("explanation") or "")[:200]
    return {
        "question": q["question"][:300],
        "options": options,
        "correct_option_id": correct_option_id,
        "explanation": explanation,
        "keys": keys,
    }
