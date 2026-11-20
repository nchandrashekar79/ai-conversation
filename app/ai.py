"""Deterministic stub AI so the API is runnable and testable without any key."""

from __future__ import annotations

import asyncio
import time

from .config import Settings


class StubAI:
    def __init__(self, model: str, latency_ms: float = 0.0) -> None:
        self.model = model
        self.latency_ms = latency_ms

    @classmethod
    def from_settings(cls, settings: Settings) -> "StubAI":
        return cls(settings.stub_model, settings.stub_latency_ms)

    async def reply(self, prompt: str, history: list[str]) -> tuple[str, dict]:
        started = time.perf_counter()
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000.0)
        else:
            await asyncio.sleep(0)

        turn = len(history)
        content = f"[{self.model}] You said: {prompt}"
        if turn:
            content += f"\n(context: {turn} earlier turn(s) in this chat)"
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return content, {"model": self.model, "latency_ms": elapsed_ms}
