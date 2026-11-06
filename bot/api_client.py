from __future__ import annotations

from typing import Any, Optional

import httpx

from bot.config import settings


class ApiClient:
    def __init__(self) -> None:
        self.base = settings.api_url
        self.headers = {"X-Import-Token": settings.import_token}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base, timeout=60.0) as client:
            r = await client.request(method, path, headers=self.headers, **kwargs)
            if r.status_code >= 400:
                detail = r.text
                try:
                    detail = r.json().get("detail", detail)
                except Exception:
                    pass
                raise RuntimeError(f"API {r.status_code}: {detail}")
            if r.status_code == 204:
                return None
            return r.json()

    async def list_tests(self, page: int = 1, size: int = 8, tag: Optional[str] = None) -> dict:
        params: dict[str, Any] = {"page": page, "size": size}
        if tag:
            params["tag"] = tag
        return await self._request("GET", "/api/tests", params=params)

    async def get_test(self, test_id: int) -> dict:
        return await self._request("GET", f"/api/tests/{test_id}")

    async def delete_test(self, test_id: int) -> dict:
        return await self._request("DELETE", f"/api/tests/{test_id}")

    async def import_payload(self, payload: Any) -> dict:
        return await self._request("POST", "/api/import", json=payload)

    async def create_attempt(self, body: dict) -> dict:
        return await self._request("POST", "/api/attempts", json=body)

    async def answer(self, attempt_id: int, question_id: int, selected: list[str]) -> dict:
        return await self._request(
            "POST",
            f"/api/attempts/{attempt_id}/answer",
            json={"question_id": question_id, "selected": selected},
        )

    async def finish(self, attempt_id: int) -> dict:
        return await self._request("POST", f"/api/attempts/{attempt_id}/finish")

    async def get_attempt(self, attempt_id: int) -> dict:
        return await self._request("GET", f"/api/attempts/{attempt_id}")

    async def active_attempts(self, telegram_user_id: str) -> dict:
        return await self._request(
            "GET",
            "/api/attempts",
            params={"active": 1, "telegram_user_id": telegram_user_id},
        )

    async def stats(self) -> dict:
        return await self._request("GET", "/api/stats")

    async def stats_topics(self) -> list:
        return await self._request("GET", "/api/stats/topics")

    async def mistakes(self) -> dict:
        return await self._request("GET", "/api/questions/mistakes")

    async def ollama_status(self) -> dict:
        return await self._request("GET", "/api/books/ollama")

    async def list_books(self) -> dict:
        return await self._request("GET", "/api/books")

    async def get_book(self, job_id: int) -> dict:
        return await self._request("GET", f"/api/books/{job_id}")

    async def upload_book_pdf(
        self, filename: str, content: bytes, title: str | None = None, telegram_user_id: str | None = None
    ) -> dict:
        files = {"file": (filename, content, "application/pdf")}
        data: dict[str, str] = {}
        if title:
            data["title"] = title
        if telegram_user_id:
            data["telegram_user_id"] = telegram_user_id
        async with httpx.AsyncClient(base_url=self.base, timeout=300.0) as client:
            r = await client.post(
                "/api/books/upload",
                headers={"X-Import-Token": settings.import_token},
                files=files,
                data=data,
            )
            if r.status_code >= 400:
                detail = r.text
                try:
                    detail = r.json().get("detail", detail)
                except Exception:
                    pass
                raise RuntimeError(f"API {r.status_code}: {detail}")
            return r.json()


api = ApiClient()
