from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_file: str | None
    max_traces: int
    stub_model: str
    stub_latency_ms: float

    @classmethod
    def from_env(cls) -> "Settings":
        data_file = os.getenv("AI_TRACE_DATA_FILE", "").strip() or None
        return cls(
            data_file=data_file,
            max_traces=_positive_int(os.getenv("AI_TRACE_MAX_TRACES"), 1000),
            stub_model=os.getenv("AI_TRACE_STUB_MODEL", "stub-echo-1"),
            stub_latency_ms=_non_negative_float(os.getenv("AI_TRACE_STUB_LATENCY_MS"), 0.0),
        )


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value > 0 else default


def _non_negative_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value >= 0 else default
