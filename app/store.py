"""Thread-safe in-memory store for chats and message traces.

Every chat turn is recorded as a trace holding both the request payload and the
AI response payload. Storage is optional-persistent: when ``data_file`` is set a
JSON snapshot is written after each mutation and loaded on startup.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


class TraceNotFound(KeyError):
    pass


class TraceStore:
    def __init__(self, data_file: str | None = None, max_traces: int = 1000) -> None:
        if max_traces < 1:
            raise ValueError("max_traces must be >= 1")
        self.max_traces = max_traces
        self.data_file = Path(data_file) if data_file else None
        self._chats: dict[str, dict[str, Any]] = {}
        self._traces: dict[str, dict[str, Any]] = {}
        self._chat_order: list[str] = []
        self._lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._loaded = False

    # ------------------------------------------------------------------ load/save

    async def ensure_loaded(self) -> None:
        """Load the snapshot once; safe to call from request middleware."""
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            await self.load()
            self._loaded = True

    async def load(self) -> None:
        if self.data_file is None or not self.data_file.exists():
            return
        raw = await asyncio.to_thread(self.data_file.read_text, encoding="utf-8")
        if not raw.strip():
            return
        snapshot = json.loads(raw)
        async with self._lock:
            self._chats = {c["id"]: c for c in snapshot.get("chats", [])}
            self._traces = {t["id"]: t for t in snapshot.get("traces", [])}
            self._chat_order = [c["id"] for c in snapshot.get("chats", [])]
            self._enforce_cap()

    async def _save(self) -> None:
        if self.data_file is None:
            return
        async with self._lock:
            payload = json.dumps(
                {"chats": list(self._chats.values()), "traces": list(self._traces.values())},
                indent=2,
            )
        await asyncio.to_thread(self._atomic_write, payload)

    def _atomic_write(self, payload: str) -> None:
        assert self.data_file is not None
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.data_file.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_path, self.data_file)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ chats

    async def create_chat(self, title: str | None) -> dict[str, Any]:
        async with self._lock:
            now = utc_now()
            chat = {
                "id": new_id(),
                "title": (title or "").strip() or "Untitled chat",
                "created_at": now,
                "updated_at": now,
                "message_count": 0,
            }
            self._chats[chat["id"]] = chat
            self._chat_order.append(chat["id"])
            self._enforce_cap()
        await self._save()
        return dict(chat)

    async def list_chats(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        async with self._lock:
            ordered = [dict(self._chats[cid]) for cid in reversed(self._chat_order) if cid in self._chats]
            return ordered[offset : offset + limit], len(ordered)

    async def get_chat(self, chat_id: str) -> dict[str, Any]:
        async with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                raise TraceNotFound(chat_id)
            return dict(chat)

    async def delete_chat(self, chat_id: str) -> tuple[int, int]:
        async with self._lock:
            if chat_id not in self._chats:
                raise TraceNotFound(chat_id)
            del self._chats[chat_id]
            self._chat_order.remove(chat_id)
            removed = [tid for tid, t in self._traces.items() if t["chat_id"] == chat_id]
            for tid in removed:
                del self._traces[tid]
        await self._save()
        return 1, len(removed)

    # ------------------------------------------------------------------ traces

    async def add_trace(
        self,
        chat_id: str,
        request_payload: dict[str, Any],
        output: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                raise TraceNotFound(chat_id)
            now = utc_now()
            trace = {
                "id": new_id(),
                "chat_id": chat_id,
                "role": "assistant",
                "input": request_payload,
                "output": output,
                "created_at": now,
            }
            self._traces[trace["id"]] = trace
            chat["message_count"] += 1
            chat["updated_at"] = now
            self._enforce_cap()
        await self._save()
        return dict(trace)

    async def list_traces(
        self, chat_id: str | None, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        async with self._lock:
            if chat_id is not None and chat_id not in self._chats:
                raise TraceNotFound(chat_id)
            items = [
                dict(t)
                for t in self._traces.values()
                if chat_id is None or t["chat_id"] == chat_id
            ]
        items.sort(key=lambda t: t["created_at"], reverse=True)
        return items[offset : offset + limit], len(items)

    async def get_trace(self, trace_id: str) -> dict[str, Any]:
        async with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                raise TraceNotFound(trace_id)
            return dict(trace)

    async def clear(self) -> tuple[int, int]:
        async with self._lock:
            counts = len(self._chats), len(self._traces)
            self._chats.clear()
            self._traces.clear()
            self._chat_order.clear()
        await self._save()
        return counts

    # ------------------------------------------------------------------ stats

    async def stats(self) -> tuple[int, int]:
        async with self._lock:
            return len(self._chats), len(self._traces)

    # ------------------------------------------------------------------ cap

    def _enforce_cap(self) -> None:
        """Drop the oldest chats (with their traces) until under ``max_traces``."""
        while len(self._traces) > self.max_traces and self._chat_order:
            oldest = self._chat_order.pop(0)
            self._chats.pop(oldest, None)
            for tid in [tid for tid, t in self._traces.items() if t["chat_id"] == oldest]:
                del self._traces[tid]
