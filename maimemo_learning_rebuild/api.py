"""Minimal Maimemo API client with read/write capability isolation."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from .guard import GuardResult


BASE_URL = "https://open.maimemo.com/open/api/v1/markji"


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict, payload: dict | None = None) -> dict: ...


class UrllibTransport:
    def request(self, method: str, url: str, headers: dict, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}") from error


class MaimemoClient:
    def __init__(self, transport: Transport, *, token: str, deck_id: str, base_url: str = BASE_URL):
        if not token:
            raise RuntimeError("MAIMEMO_TOKEN is required")
        self._transport = transport
        self._token = token
        self.deck_id = deck_id
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_environment(cls, *, deck_id: str) -> "MaimemoClient":
        return cls(UrllibTransport(), token=os.environ.get("MAIMEMO_TOKEN", ""), deck_id=deck_id)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        try:
            response = self._transport.request(method, self.base_url + path, headers, payload)
            if response.get("errors"):
                raise RuntimeError(str(response["errors"]))
            return response.get("data", {})
        except Exception as error:
            message = str(error).replace(self._token, "[REDACTED]")
            raise RuntimeError(message) from error

    def read_deck(self) -> dict:
        return self._request("GET", f"/decks/{self.deck_id}/chapters?with_cards=true")

    @staticmethod
    def _require_guard(guard: GuardResult) -> None:
        if not guard.ok:
            raise RuntimeError("write requires approved guard")

    def update_card(self, card_id: str, content: str, guard: GuardResult) -> dict:
        self._require_guard(guard)
        return self._request(
            "POST",
            f"/decks/{self.deck_id}/cards/{card_id}",
            {"card": {"content": content, "grammar_version": 3}},
        )

    def create_card(self, chapter_id: str, content: str, guard: GuardResult) -> dict:
        self._require_guard(guard)
        return self._request(
            "POST",
            f"/decks/{self.deck_id}/chapters/{chapter_id}/cards",
            {"card": {"content": content, "grammar_version": 3}},
        )
