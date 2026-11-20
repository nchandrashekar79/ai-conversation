"""Pydantic schemas for the trace API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class Chat(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)


class TraceOutput(BaseModel):
    content: str
    model: str
    latency_ms: float


class Trace(BaseModel):
    id: str
    chat_id: str
    role: str = "assistant"
    input: dict[str, Any]
    output: TraceOutput
    created_at: str


class ChatReply(BaseModel):
    chat: Chat
    message: Trace


class ChatList(BaseModel):
    items: list[Chat]
    total: int


class TraceList(BaseModel):
    items: list[Trace]
    total: int


class Health(BaseModel):
    status: str
    chats: int
    traces: int
    max_traces: int
    persistence: bool


class ClearResult(BaseModel):
    deleted_chats: int
    deleted_traces: int
