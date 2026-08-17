"""Append-only, non-secret journal with a single-writer lock."""

from __future__ import annotations

import json
import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


JOURNAL_FIELDS = frozenset(
    {
        "release_hash",
        "title",
        "action",
        "stable_card_key",
        "card_id",
        "root_id",
        "content_hash",
        "outcome",
        "timestamp",
        "github_run_id",
    }
)


class ReleaseJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock_stream = None

    def acquire(self) -> bool:
        if self._lock_stream is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.path.getsize(self.lock_path) == 0:
                stream.write(b"\0")
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._lock_stream = stream
        return True

    def release(self) -> None:
        if self._lock_stream is None:
            return
        try:
            self._lock_stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_stream.close()
            self._lock_stream = None

    def record(self, entry: dict) -> None:
        if not isinstance(entry, dict) or not set(entry) <= JOURNAL_FIELDS:
            raise ValueError("journal fields are not permitted")
        raw = json.dumps(
            entry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(raw + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        values = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict) or not set(value) <= JOURNAL_FIELDS:
                    raise ValueError("journal fields are not permitted")
                values.append(value)
        return values

    def __enter__(self) -> "ReleaseJournal":
        if not self.acquire():
            raise RuntimeError("release writer is already running")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
