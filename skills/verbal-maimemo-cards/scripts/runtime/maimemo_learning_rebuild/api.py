"""Minimal Maimemo API client with read/write capability isolation."""

from __future__ import annotations

import json
import email.utils
import math
import socket
from datetime import datetime, timezone
import urllib.error
import urllib.request
from typing import Protocol

from .guard import GuardResult


BASE_URL = "https://open.maimemo.com/open/api/v1/markji"
MAX_RETRY_AFTER_SECONDS = 3600.0


class AmbiguousMutationError(RuntimeError):
    """A mutation may have reached the server, so callers must read before retrying."""


class PermanentApiError(RuntimeError):
    """A definitive API rejection that must not be retried as a mutation."""


class RateLimitError(RuntimeError):
    """A definitive 429 response with a finite, bounded server delay."""

    def __init__(self, retry_after_seconds: float, message: str = "HTTP 429"):
        delay = float(retry_after_seconds)
        if not math.isfinite(delay) or delay < 0 or delay > MAX_RETRY_AFTER_SECONDS:
            raise ValueError("Retry-After is not finite and bounded")
        super().__init__(message)
        self.retry_after_seconds = delay


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        delay = float(value.strip())
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            raise PermanentApiError("invalid Retry-After header")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        try:
            delay = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (OverflowError, OSError, ValueError) as error:
            raise PermanentApiError("invalid Retry-After header") from error
    if not math.isfinite(delay) or delay < 0 or delay > MAX_RETRY_AFTER_SECONDS:
        raise PermanentApiError("invalid Retry-After header")
    return delay


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _strict_response(response) -> dict:
    raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    if not isinstance(raw, str):
        raise ValueError("API response must be UTF-8 JSON")
    value = json.loads(
        raw,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_json_object,
    )
    if not isinstance(value, dict):
        raise ValueError("API response must be an object")
    return value


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict, payload: dict | None = None) -> dict: ...


class UrllibTransport:
    def request(self, method: str, url: str, headers: dict, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                try:
                    return _strict_response(response)
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as error:
                    if method == "POST":
                        raise AmbiguousMutationError("mutation response was not strict JSON") from error
                    raise PermanentApiError("API response was not strict JSON") from error
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise RateLimitError(
                    _retry_after_seconds(error.headers.get("Retry-After"))
                ) from error
            if method == "POST" and error.code >= 500:
                raise AmbiguousMutationError(f"HTTP {error.code}") from error
            raise PermanentApiError(f"HTTP {error.code}") from error
        except (TimeoutError, socket.timeout, urllib.error.URLError) as error:
            if method == "POST":
                raise AmbiguousMutationError("mutation response was not received") from error
            raise PermanentApiError("API response was not received") from error


class MaimemoClient:
    def __init__(self, transport: Transport, *, token: str, deck_id: str, base_url: str = BASE_URL):
        if not token:
            raise RuntimeError("MAIMEMO_TOKEN is required")
        self._transport = transport
        self._token = token
        self.deck_id = deck_id
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        try:
            response = self._transport.request(method, self.base_url + path, headers, payload)
            if response.get("errors"):
                raise PermanentApiError(str(response["errors"]))
            return response.get("data", {})
        except Exception as error:
            message = str(error).replace(self._token, "[REDACTED]")
            message = message.replace(f"Bearer {self._token}", "Bearer [REDACTED]")
            if isinstance(error, RateLimitError):
                raise RateLimitError(error.retry_after_seconds, message) from error
            if isinstance(error, AmbiguousMutationError):
                raise AmbiguousMutationError(message) from error
            if isinstance(error, PermanentApiError):
                raise PermanentApiError(message) from error
            if method == "POST":
                raise AmbiguousMutationError(message) from error
            raise PermanentApiError(message) from error

    def read_deck(self) -> dict:
        return self._request("GET", f"/decks/{self.deck_id}/chapters?with_cards=true")

    @staticmethod
    def _require_guard(guard: GuardResult) -> None:
        if not guard.ok:
            raise RuntimeError("write requires approved guard")
        if (
            not isinstance(guard.learning_review_hash, str)
            or not guard.learning_review_hash.strip()
        ):
            raise RuntimeError("write requires approved guard with learning review")

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
