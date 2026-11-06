from __future__ import annotations

import asyncio
from pathlib import Path
import html
import json
import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    Message,
    PollAnswer,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import keyboards as kb
from bot.api_client import api
from bot.config import settings
from bot.quiz import format_feedback, format_finish, format_question, build_poll

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("bot")

# in-memory reminders + last finish mistakes for review
REMINDERS: dict[int, bool] = {}
LAST_FINISH: dict[int, dict] = {}
POLL_MAP: dict[str, dict] = {}  # poll_id -> meta
JSON_BUF: dict[int, list[str]] = {}


class QuizFSM(StatesGroup):
    answering = State()
    multi_select = State()
    waiting_json = State()


def allowed(user_id: int | None) -> bool:
    if not settings.allowed_user_ids:
        return False
    return user_id in settings.allowed_user_ids


def extract_json(text: str) -> Any:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
    if m:
        t = m.group(1).strip()
    return json.loads(t)


async def show_tests(message: Message, page: int = 1) -> None:
    data = await api.list_tests(page=page, size=8)
    items = data.get("items") or []
    total = data.get("total") or 0
    if not items:
        await message.answer("Тестов пока нет. Пришлите JSON или /import.")
        return
    await message.answer(
        f"📚 Тесты (стр. {page})",
        reply_markup=kb.tests_page(items, page, total, size=8),
    )


async def send_question(bot: Bot, chat_id: int, message_id: int | None, attempt: dict, idx: int, state: FSMContext):
    body, markup, code_msg = format_question(attempt, idx)
    q = attempt["questions"][idx]
    await state.update_data(
        attempt=attempt,
        idx=idx,
        selected=[],
        answered=False,
        message_id=message_id,
        chat_id=chat_id,
    )
    if code_msg and message_id is None:
        await bot.send_message(chat_id, code_msg, parse_mode="HTML")
    elif code_msg and message_id is not None:
        await bot.send_message(chat_id, code_msg, parse_mode="HTML")

    if q.get("type") == "multiple":
        await state.set_state(QuizFSM.multi_select)
        await state.update_data(selected=[])
    else:
        await state.set_state(QuizFSM.answering)

    if message_id is None:
        msg = await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)
        await state.update_data(message_id=msg.message_id)
    else:
        try:
            await bot.edit_message_text(
                body, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=markup
            )
        except Exception:
            msg = await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)
            await state.update_data(message_id=msg.message_id)


async def start_attempt_flow(
    message: Message,
    state: FSMContext,
    *,
    test_id: int | None = None,
    mode: str = "full",
    shuffle: bool = False,
    tag: str | None = None,
    limit: int | None = None,
):
    body: dict[str, Any] = {
        "test_id": test_id,
        "mode": mode,
        "shuffle": shuffle,
        "telegram_user_id": str(message.from_user.id),
    }
    if tag:
        body["tag"] = tag
    if limit:
        body["limit"] = limit
    if mode == "random" and not limit:
        body["limit"] = 10
    attempt = await api.create_attempt(body)
    await send_question(message.bot, message.chat.id, None, attempt, 0, state)


def create_bot() -> Bot:
    if settings.tg_proxy:
        session = AiohttpSession(proxy=settings.tg_proxy)
        return Bot(token=settings.bot_token, session=session)
    return Bot(token=settings.bot_token)


def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message.middleware()
    async def acl_message(handler, event: Message, data):
        if not allowed(event.from_user.id if event.from_user else None):
            return
        return await handler(event, data)

    @dp.callback_query.middleware()
    async def acl_cb(handler, event: CallbackQuery, data):
        if not allowed(event.from_user.id if event.from_user else None):
            await event.answer()
            return
        return await handler(event, data)

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(
            f"Привет! Веб: {settings.web_url}\nВыбери действие в меню.",
            reply_markup=kb.main_menu(),
        )

    @dp.message(Command("tests"))
    @dp.message(F.text == "📚 Тесты")
    async def cmd_tests(message: Message):
        await show_tests(message, 1)

    @dp.message(Command("mistakes"))
    @dp.message(F.text == "🔁 Ошибки")
    async def cmd_mistakes(message: Message, state: FSMContext):
        await start_attempt_flow(message, state, mode="mistakes", shuffle=True)

    @dp.message(Command("random"))
    @dp.message(F.text == "🎲 Случайные")
    async def cmd_random(message: Message, state: FSMContext, command: CommandObject | None = None):
        tag = None
        n = 10
        if command and command.args:
            parts = command.args.split()
            for p in parts:
                if p.isdigit():
                    n = int(p)
                else:
                    tag = p
        await start_attempt_flow(message, state, mode="random", tag=tag, limit=n, shuffle=True)

    @dp.message(Command("stats"))
    @dp.message(F.text == "📊 Статистика")
    async def cmd_stats(message: Message):
        data = await api.stats()
        lines = ["<b>По темам</b>"]
        for t in data.get("topics") or []:
            pct = int(round(t["percent"] / 10))
            bar = "█" * pct + "░" * (10 - pct)
            lines.append(f"{html.escape(t['topic'])}: {t['percent']}% {bar}")
        lines.append("\n<b>Топ проблемных</b>")
        for q in (data.get("problematic_questions") or [])[:5]:
            lines.append(f"· {q['percent']}% — {html.escape(q['question'][:120])}")
        await message.answer("\n".join(lines) or "Пока пусто", parse_mode="HTML")

    @dp.message(Command("continue"))
    async def cmd_continue(message: Message, state: FSMContext):
        data = await api.active_attempts(str(message.from_user.id))
        items = data.get("items") or []
        if not items:
            await message.answer("Нет незавершённых попыток.")
            return
        attempt_state = items[0]
        answered = set(map(int, (attempt_state.get("answers") or {}).keys()))
        questions = attempt_state["questions"]
        idx = next((i for i, q in enumerate(questions) if q["id"] not in answered), len(questions) - 1)
        attempt = {
            "attempt_id": attempt_state["attempt_id"],
            "total": attempt_state["total"],
            "questions": questions,
            "mode": attempt_state["mode"],
        }
        await send_question(message.bot, message.chat.id, None, attempt, idx, state)

    @dp.message(Command("stop"))
    async def cmd_stop(message: Message, state: FSMContext):
        data = await state.get_data()
        attempt = data.get("attempt")
        if not attempt:
            await message.answer("Нет активной попытки в этом чате.")
            return
        result = await api.finish(attempt["attempt_id"])
        LAST_FINISH[message.from_user.id] = result
        await state.clear()
        await message.answer(format_finish(result), parse_mode="HTML", reply_markup=kb.finish_kb())

    @dp.message(Command("remind"))
    async def cmd_remind(message: Message, command: CommandObject):
        arg = (command.args or "").strip().lower()
        uid = message.from_user.id
        if arg == "on":
            REMINDERS[uid] = True
            await message.answer("Напоминания включены.")
        elif arg == "off":
            REMINDERS[uid] = False
            await message.answer("Напоминания выключены.")
        else:
            await message.answer("Использование: /remind on|off")

    @dp.message(Command("import"))
    @dp.message(F.text == "📥 Импорт")
    async def cmd_import(message: Message, state: FSMContext):
        await state.set_state(QuizFSM.waiting_json)
        await message.answer(
            "Пришлите .json документ, JSON-текст или блок:\n/start_json … /end"
        )

    @dp.message(Command("start_json"))
    async def cmd_start_json(message: Message):
        JSON_BUF[message.from_user.id] = []
        await message.answer("Жду JSON. Завершите командой /end")

    @dp.message(Command("end"))
    async def cmd_end_json(message: Message):
        buf = JSON_BUF.pop(message.from_user.id, [])
        if not buf:
            await message.answer("Буфер пуст. Начните с /start_json")
            return
        await _import_text(message, "\n".join(buf))

    @dp.message(Command("quiz"))
    async def cmd_quiz(message: Message, command: CommandObject, state: FSMContext):
        tag = (command.args or "").strip() or None
        attempt = await api.create_attempt(
            {
                "mode": "random",
                "tag": tag,
                "limit": 5,
                "shuffle": True,
                "telegram_user_id": str(message.from_user.id),
            }
        )
        # need correct answers for poll — fetch test editor data per question via mistakes? 
        # Poll needs correct_option_id; public attempt has no correct.
        # Fetch full tests and match by question id.
        tests = await api.list_tests(page=1, size=100)
        full_map: dict[int, dict] = {}
        for t in tests.get("items") or []:
            full = await api.get_test(t["id"])
            for q in full.get("questions") or []:
                full_map[q["id"]] = q

        sent = 0
        for qpub in attempt["questions"]:
            q = full_map.get(qpub["id"])
            if not q:
                continue
            poll = build_poll(q)
            if not poll:
                continue
            msg = await message.answer_poll(
                question=poll["question"],
                options=poll["options"],
                type="quiz",
                correct_option_id=poll["correct_option_id"],
                is_anonymous=False,
                explanation=poll["explanation"] or None,
            )
            POLL_MAP[msg.poll.id] = {
                "attempt_id": attempt["attempt_id"],
                "question_id": q["id"],
                "keys": poll["keys"],
                "user_id": message.from_user.id,
            }
            sent += 1
        if not sent:
            await message.answer("Нет подходящих вопросов для poll-квиза.")
            await api.finish(attempt["attempt_id"])
        else:
            await state.update_data(poll_attempt_id=attempt["attempt_id"], poll_sent=sent)

    @dp.poll_answer()
    async def on_poll_answer(answer: PollAnswer):
        meta = POLL_MAP.get(answer.poll_id)
        if not meta or answer.user.id != meta["user_id"]:
            return
        if not answer.option_ids:
            return
        key = meta["keys"][answer.option_ids[0]]
        try:
            await api.answer(meta["attempt_id"], meta["question_id"], [key])
        except Exception as exc:
            logger.warning("poll answer failed: %s", exc)

    @dp.message(Command("book"))
    @dp.message(F.text == "📖 Книга PDF")
    async def cmd_book(message: Message):
        st = await api.ollama_status()
        line = (
            f"Ollama: OK, model={st.get('configured')}"
            if st.get("ok")
            else f"Ollama недоступен: {st.get('error')}"
        )
        await message.answer(
            "Пришлите PDF-книгу (документ).\n"
            "Я очищу текст → отдам Qwen (Ollama) → сделаю ~1 тест на страницу\n"
            f"в examples/&lt;книга&gt;/&lt;тема&gt;.json\n\n{html.escape(line)}",
            parse_mode="HTML",
        )

    @dp.message(Command("books"))
    async def cmd_books(message: Message):
        data = await api.list_books()
        items = data.get("items") or []
        if not items:
            await message.answer("Задач по книгам пока нет.")
            return
        lines = []
        for j in items[:15]:
            lines.append(
                f"#{j['id']} {html.escape(j['title'])} — <b>{j['status']}</b> "
                f"({j['pages_done']}/{j['page_count']}, тестов {j['tests_generated']})"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    @dp.message(F.document)
    async def on_document(message: Message, state: FSMContext):
        doc = message.document
        if not doc.file_name:
            return
        name = doc.file_name.lower()
        file = await message.bot.get_file(doc.file_id)
        bio = await message.bot.download_file(file.file_path)
        raw = bio.read()
        if name.endswith(".json"):
            text = raw.decode("utf-8")
            await _import_text(message, text)
            await state.clear()
            return
        if not name.endswith(".pdf"):
            return
        await message.answer("📖 Принял PDF, ставлю в очередь генерации…")
        try:
            title = Path(doc.file_name).stem
            job = await api.upload_book_pdf(
                doc.file_name,
                raw,
                title=title,
                telegram_user_id=str(message.from_user.id),
            )
        except Exception as exc:
            await message.answer(f"Ошибка загрузки: {html.escape(str(exc))}", parse_mode="HTML")
            return
        await message.answer(
            f"Задача <b>#{job['id']}</b> «{html.escape(job['title'])}»\n"
            f"Раздел: <code>examples/{html.escape(job['slug'])}/</code>\n"
            f"Статус: {job['status']}. Буду писать прогресс.",
            parse_mode="HTML",
        )
        asyncio.create_task(_watch_book_job(message, job["id"]))

    async def _watch_book_job(message: Message, job_id: int):
        last = ""
        for _ in range(600):  # up to ~50 min with 5s
            await asyncio.sleep(5)
            try:
                job = await api.get_book(job_id)
            except Exception as exc:
                await message.answer(f"Не удалось получить статус #{job_id}: {exc}")
                return
            status = job.get("status")
            prog = f"{job.get('pages_done', 0)}/{job.get('page_count', 0)} · тестов {job.get('tests_generated', 0)}"
            line = f"#{job_id} {status}: {prog}"
            if line != last and status in ("extracting", "generating", "done", "failed"):
                last = line
                if status in ("done", "failed") or job.get("pages_done", 0) % 5 == 0:
                    extra = f"\n{html.escape(job.get('error') or '')}" if job.get("error") else ""
                    await message.answer(
                        f"📖 {html.escape(job.get('title') or '')}\n{html.escape(line)}{extra}\n"
                        f"<code>examples/{html.escape(job.get('slug') or '')}/</code>",
                        parse_mode="HTML",
                    )
            if status in ("done", "failed"):
                return

    @dp.message(QuizFSM.waiting_json)
    @dp.message(F.text.regexp(r"^\s*[\[{]"))
    async def on_json_text(message: Message, state: FSMContext):
        uid = message.from_user.id
        if uid in JSON_BUF:
            JSON_BUF[uid].append(message.text or "")
            return
        try:
            await _import_text(message, message.text or "")
            await state.clear()
        except Exception:
            if await state.get_state() == QuizFSM.waiting_json.state:
                await message.answer("Не удалось разобрать JSON. Пришлите ещё раз или файл.")

    async def _import_text(message: Message, text: str):
        try:
            payload = extract_json(text)
            res = await api.import_payload(payload)
            for item in res.get("imported") or []:
                await message.answer(
                    f"✅ {item['title']} — {item['question_count']} вопросов",
                    reply_markup=kb.after_import(item["id"]),
                )
        except Exception as exc:
            await message.answer(f"Ошибка импорта: {html.escape(str(exc))}", parse_mode="HTML")

    @dp.callback_query(F.data.startswith("tests_page:"))
    async def cb_tests_page(cq: CallbackQuery):
        page = int(cq.data.split(":")[1])
        data = await api.list_tests(page=page, size=8)
        await cq.message.edit_text(
            f"📚 Тесты (стр. {page})",
            reply_markup=kb.tests_page(data.get("items") or [], page, data.get("total") or 0),
        )
        await cq.answer()

    @dp.callback_query(F.data.startswith("test:"))
    async def cb_test(cq: CallbackQuery):
        test_id = int(cq.data.split(":")[1])
        t = await api.get_test(test_id)
        tags = ", ".join(t.get("tags") or []) or "—"
        text = (
            f"<b>{html.escape(t['title'])}</b>\n"
            f"{html.escape(t.get('description') or '')}\n"
            f"Теги: {html.escape(tags)}\n"
            f"Вопросов: {len(t.get('questions') or [])}"
        )
        await cq.message.edit_text(text, parse_mode="HTML", reply_markup=kb.test_card(test_id))
        await cq.answer()

    @dp.callback_query(F.data.startswith("delask:"))
    async def cb_delask(cq: CallbackQuery):
        test_id = int(cq.data.split(":")[1])
        await cq.message.edit_reply_markup(reply_markup=kb.confirm_delete(test_id))
        await cq.answer("Подтвердите удаление")

    @dp.callback_query(F.data.startswith("del:"))
    async def cb_del(cq: CallbackQuery):
        test_id = int(cq.data.split(":")[1])
        await api.delete_test(test_id)
        await cq.message.edit_text("Тест удалён.")
        await cq.answer()

    @dp.callback_query(F.data.startswith("run:"))
    async def cb_run(cq: CallbackQuery, state: FSMContext):
        _, tid, mode, sh = cq.data.split(":")
        test_id = int(tid)
        shuffle = sh == "1"
        limit = 10 if mode == "random" else None
        try:
            attempt = await api.create_attempt(
                {
                    "test_id": test_id,
                    "mode": mode,
                    "shuffle": shuffle,
                    "limit": limit,
                    "telegram_user_id": str(cq.from_user.id),
                }
            )
        except Exception as exc:
            await cq.answer(str(exc)[:180], show_alert=True)
            return
        await cq.answer()
        await send_question(cq.bot, cq.message.chat.id, None, attempt, 0, state)

    @dp.callback_query(F.data.startswith("ans:"))
    async def cb_ans(cq: CallbackQuery, state: FSMContext):
        _, aid, idx_s, key = cq.data.split(":", 3)
        await _submit(cq, state, int(aid), int(idx_s), [key])

    @dp.callback_query(F.data.startswith("tgl:"))
    async def cb_tgl(cq: CallbackQuery, state: FSMContext):
        _, aid, idx_s, key = cq.data.split(":", 3)
        data = await state.get_data()
        if data.get("answered"):
            await cq.answer("Уже отвечено", show_alert=True)
            return
        selected = set(data.get("selected") or [])
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        await state.update_data(selected=list(selected))
        attempt = data["attempt"]
        idx = int(idx_s)
        q = attempt["questions"][idx]
        keys = list(q["options"].keys())
        markup = kb.multiple_options(int(aid), idx, keys, selected)
        await cq.message.edit_reply_markup(reply_markup=markup)
        await cq.answer()

    @dp.callback_query(F.data.startswith("chk:"))
    async def cb_chk(cq: CallbackQuery, state: FSMContext):
        _, aid, idx_s = cq.data.split(":")
        data = await state.get_data()
        selected = data.get("selected") or []
        if not selected:
            await cq.answer("Выберите хотя бы один вариант", show_alert=True)
            return
        await _submit(cq, state, int(aid), int(idx_s), list(selected))

    @dp.callback_query(F.data.startswith("skip:"))
    async def cb_skip(cq: CallbackQuery, state: FSMContext):
        _, aid, idx_s = cq.data.split(":")
        data = await state.get_data()
        attempt = data.get("attempt") or {"attempt_id": int(aid), "questions": [], "total": 0}
        idx = int(idx_s) + 1
        if idx >= attempt["total"]:
            result = await api.finish(int(aid))
            LAST_FINISH[cq.from_user.id] = result
            await state.clear()
            await cq.message.edit_text(format_finish(result), parse_mode="HTML", reply_markup=kb.finish_kb())
            await cq.answer()
            return
        await cq.answer("Пропущено")
        await send_question(cq.bot, cq.message.chat.id, cq.message.message_id, attempt, idx, state)

    @dp.callback_query(F.data.startswith("stop:"))
    async def cb_stop(cq: CallbackQuery, state: FSMContext):
        aid = int(cq.data.split(":")[1])
        result = await api.finish(aid)
        LAST_FINISH[cq.from_user.id] = result
        await state.clear()
        await cq.message.edit_text(format_finish(result), parse_mode="HTML", reply_markup=kb.finish_kb())
        await cq.answer()

    @dp.callback_query(F.data.startswith("nxt:"))
    async def cb_nxt(cq: CallbackQuery, state: FSMContext):
        _, aid, idx_s = cq.data.split(":")
        data = await state.get_data()
        attempt = data["attempt"]
        idx = int(idx_s) + 1
        if idx >= attempt["total"]:
            result = await api.finish(int(aid))
            LAST_FINISH[cq.from_user.id] = result
            await state.clear()
            await cq.message.edit_text(format_finish(result), parse_mode="HTML", reply_markup=kb.finish_kb())
            await cq.answer()
            return
        await cq.answer()
        await send_question(cq.bot, cq.message.chat.id, cq.message.message_id, attempt, idx, state)

    @dp.callback_query(F.data.startswith("menu:"))
    async def cb_menu(cq: CallbackQuery, state: FSMContext):
        action = cq.data.split(":")[1]
        await cq.answer()
        if action == "tests":
            await show_tests(cq.message, 1)
        elif action == "mistakes":
            await start_attempt_flow(cq.message, state, mode="mistakes", shuffle=True)
        elif action == "mistakes5":
            await start_attempt_flow(cq.message, state, mode="mistakes", shuffle=True, limit=5)
        elif action == "review":
            result = LAST_FINISH.get(cq.from_user.id)
            if not result or not result.get("mistakes"):
                await cq.message.answer("Нет разбора ошибок.")
                return
            for m in result["mistakes"]:
                text = (
                    f"<b>{html.escape(m['question'])}</b>\n"
                    f"Твой: {html.escape(', '.join(m.get('selected') or []) or '—')}\n"
                    f"Верно: {html.escape(', '.join(m.get('correct') or []))}\n"
                    f"💡 {html.escape(m.get('explanation') or '')}"
                )
                await cq.message.answer(text, parse_mode="HTML")

    @dp.callback_query(F.data == "noop")
    async def cb_noop(cq: CallbackQuery):
        await cq.answer()

    async def _submit(cq: CallbackQuery, state: FSMContext, attempt_id: int, idx: int, selected: list[str]):
        data = await state.get_data()
        if data.get("answered"):
            await cq.answer("Уже отвечено", show_alert=True)
            return
        attempt = data.get("attempt")
        if not attempt or attempt["attempt_id"] != attempt_id:
            await cq.answer("Сессия устарела", show_alert=True)
            return
        q = attempt["questions"][idx]
        try:
            ans = await api.answer(attempt_id, q["id"], selected)
        except Exception as exc:
            await cq.answer(str(exc)[:180], show_alert=True)
            return
        if ans.get("already_answered"):
            await cq.answer("Уже отвечено", show_alert=True)
            return
        await state.update_data(answered=True)
        await cq.answer("✅" if ans.get("is_correct") else "❌")
        feedback = format_feedback(q, ans, selected)
        # prepend short question title
        text = f"<b>Вопрос {idx + 1}/{attempt['total']}</b>\n{feedback}"
        await cq.message.edit_text(text, parse_mode="HTML", reply_markup=kb.after_answer(attempt_id, idx))

    return dp


async def reminder_job(bot: Bot):
    for uid, enabled in list(REMINDERS.items()):
        if not enabled:
            continue
        try:
            await bot.send_message(
                uid,
                "Пора повторить: 5 вопросов из ошибок 🔁",
                reply_markup=kb.remind_start(),
            )
        except Exception:
            logger.exception("reminder failed for %s", uid)


async def main() -> None:
    if not settings.bot_token:
        logger.warning("BOT_TOKEN is empty — bot idle (set token in .env to enable)")
        while True:
            await asyncio.sleep(3600)
    bot = create_bot()
    dp = setup_dispatcher()
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Меню"),
            BotCommand(command="tests", description="Список тестов"),
            BotCommand(command="random", description="Случайные вопросы"),
            BotCommand(command="mistakes", description="Только ошибки"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="continue", description="Продолжить попытку"),
            BotCommand(command="stop", description="Завершить попытку"),
            BotCommand(command="import", description="Импорт JSON"),
            BotCommand(command="quiz", description="Быстрый quiz-poll"),
            BotCommand(command="remind", description="Напоминания on|off"),
            BotCommand(command="book", description="Книга PDF → тесты"),
            BotCommand(command="books", description="Статус задач книг"),
        ]
    )
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.tz))
    hour, minute = settings.reminder_time.split(":")
    scheduler.add_job(reminder_job, "cron", hour=int(hour), minute=int(minute), args=[bot])
    scheduler.start()
    logger.info("Bot polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
