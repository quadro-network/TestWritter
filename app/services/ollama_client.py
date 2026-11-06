from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("ollama")


class OllamaError(RuntimeError):
    pass


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if m:
        text = m.group(1).strip()
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj == -1 and start_arr == -1:
        raise OllamaError("no JSON object in model response")
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        start = start_arr
        end = text.rfind("]")
    else:
        start = start_obj
        end = text.rfind("}")
    if end == -1 or end < start:
        raise OllamaError("truncated JSON in model response")
    return json.loads(text[start : end + 1])


async def _chat_once(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> str:
    """
    stream=true: tokens arrive immediately. With stream=false there is ~30s of
    silence, Docker/WSL drops the TCP connection ("Server disconnected"), and
    Ollama cancels the request with HTTP 500.
    """
    parts: list[str] = []
    async with client.stream("POST", url, json=payload) as r:
        if r.status_code >= 400:
            body = (await r.aread()).decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"Ollama HTTP {r.status_code}: {body}")
        async for line in r.aiter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if err := chunk.get("error"):
                raise OllamaError(f"Ollama error: {err}")
            msg = chunk.get("message") or {}
            piece = msg.get("content") or ""
            if piece:
                parts.append(piece)
            if chunk.get("done"):
                break
    content = "".join(parts).strip()
    if not content:
        raise OllamaError("empty Ollama response")
    return content


async def ollama_chat_json(system: str, user: str, *, temperature: float = 0.3) -> Any:
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    model = settings.ollama_model
    if not base:
        raise OllamaError("OLLAMA_BASE_URL is empty")

    payload = {
        "model": model,
        "stream": True,
        "format": "json",
        "options": {
            "temperature": temperature,
            # 15-question JSON is ~2–4k tokens; 6k is enough and fits the slot sooner
            "num_predict": 6144,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    url = f"{base}/api/chat"
    timeout = httpx.Timeout(
        connect=30.0,
        read=float(settings.ollama_timeout),
        write=120.0,
        pool=30.0,
    )
    last_exc: Exception | None = None
    attempts = max(1, int(getattr(settings, "ollama_retries", 5)))
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, attempts + 1):
            try:
                content = await _chat_once(client, url, payload)
                try:
                    return _extract_json(content)
                except json.JSONDecodeError as exc:
                    logger.warning("JSON parse failed, raw=%s", content[:400])
                    raise OllamaError(f"invalid JSON from model: {exc}") from exc
            except (httpx.RequestError, OllamaError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                wait = min(25, 3 * attempt)
                logger.warning(
                    "Ollama attempt %s/%s failed: %s — retry in %ss",
                    attempt,
                    attempts,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
    raise OllamaError(
        f"Ollama request failed at {base} after {attempts} tries "
        f"(часто обрыв long-poll/proxy ~30с; нужен stream). Last: {last_exc}"
    ) from last_exc


async def ollama_ping() -> dict[str, Any]:
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            models = [m.get("name") for m in (r.json().get("models") or [])]
            return {
                "ok": True,
                "base_url": base,
                "models": models,
                "configured": settings.ollama_model,
            }
        except Exception as exc:
            return {
                "ok": False,
                "base_url": base,
                "error": str(exc),
                "configured": settings.ollama_model,
            }
