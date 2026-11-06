from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Тесты"), KeyboardButton(text="🔁 Ошибки")],
            [KeyboardButton(text="🎲 Случайные"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📥 Импорт"), KeyboardButton(text="📖 Книга PDF")],
        ],
        resize_keyboard=True,
    )


def tests_page(items: list[dict], page: int, total: int, size: int = 8) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in items:
        best = f"{t['best_percent']:.0f}%" if t.get("best_percent") is not None else "—"
        b.button(text=f"{t['title'][:40]} ({best})", callback_data=f"test:{t['id']}")
    b.adjust(1)
    pages = max(1, (total + size - 1) // size)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"tests_page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"tests_page:{page + 1}"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def test_card(test_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶ Все по порядку", callback_data=f"run:{test_id}:full:0")
    b.button(text="🔀 Перемешать", callback_data=f"run:{test_id}:full:1")
    b.button(text="🔁 Только ошибки", callback_data=f"run:{test_id}:mistakes:0")
    b.button(text="🗑 Удалить", callback_data=f"delask:{test_id}")
    b.adjust(1)
    return b.as_markup()


def confirm_delete(test_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да, удалить", callback_data=f"del:{test_id}")
    b.button(text="Отмена", callback_data=f"test:{test_id}")
    b.adjust(2)
    return b.as_markup()


def after_import(test_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶ Пройти", callback_data=f"run:{test_id}:full:0")
    b.button(text="🎲 10 случайных", callback_data=f"run:{test_id}:random:1")
    b.adjust(2)
    return b.as_markup()


def single_options(attempt_id: int, idx: int, keys: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for k in keys:
        b.button(text=k, callback_data=f"ans:{attempt_id}:{idx}:{k}")
    b.adjust(4)
    b.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{attempt_id}:{idx}"),
        InlineKeyboardButton(text="⏹ Завершить", callback_data=f"stop:{attempt_id}"),
    )
    return b.as_markup()


def true_false(attempt_id: int, idx: int, keys: list[str]) -> InlineKeyboardMarkup:
    # map first/second or true/false
    true_key = next((k for k in keys if k.lower() in ("true", "верно", "a", "yes")), keys[0])
    false_key = next((k for k in keys if k != true_key), keys[-1])
    b = InlineKeyboardBuilder()
    b.button(text="✅ Верно", callback_data=f"ans:{attempt_id}:{idx}:{true_key}")
    b.button(text="❌ Неверно", callback_data=f"ans:{attempt_id}:{idx}:{false_key}")
    b.adjust(2)
    b.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{attempt_id}:{idx}"),
        InlineKeyboardButton(text="⏹ Завершить", callback_data=f"stop:{attempt_id}"),
    )
    return b.as_markup()


def multiple_options(
    attempt_id: int, idx: int, keys: list[str], selected: set[str]
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for k in keys:
        mark = "☑" if k in selected else "☐"
        b.button(text=f"{mark} {k}", callback_data=f"tgl:{attempt_id}:{idx}:{k}")
    b.adjust(4)
    b.row(InlineKeyboardButton(text="✔ Проверить", callback_data=f"chk:{attempt_id}:{idx}"))
    b.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{attempt_id}:{idx}"),
        InlineKeyboardButton(text="⏹ Завершить", callback_data=f"stop:{attempt_id}"),
    )
    return b.as_markup()


def after_answer(attempt_id: int, idx: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➡ Далее", callback_data=f"nxt:{attempt_id}:{idx}")
    return b.as_markup()


def finish_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Повторить ошибки", callback_data="menu:mistakes")
    b.button(text="📋 Разбор ошибок", callback_data="menu:review")
    b.button(text="📚 К тестам", callback_data="menu:tests")
    b.adjust(1)
    return b.as_markup()


def remind_start() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶ Начать", callback_data="menu:mistakes5")
    return b.as_markup()
