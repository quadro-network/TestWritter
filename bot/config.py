from __future__ import annotations

import os


def _split_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


class BotSettings:
    def __init__(self) -> None:
        self.bot_token = os.getenv("BOT_TOKEN", "").strip()
        self.allowed_user_ids = _split_ids(os.getenv("ALLOWED_USER_IDS", ""))
        self.api_url = os.getenv("API_URL", "http://app:8000").rstrip("/")
        self.import_token = os.getenv("IMPORT_TOKEN", "")
        self.tg_proxy = os.getenv("TG_PROXY") or None
        self.web_url = os.getenv("WEB_URL", "http://127.0.0.1:2323")
        self.tz = os.getenv("TZ", "Europe/Moscow")
        self.reminder_time = os.getenv("REMINDER_TIME", "09:00")


settings = BotSettings()
