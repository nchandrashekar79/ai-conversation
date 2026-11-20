"""FastAPI application exposing the in-memory AI chat trace API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .ai import StubAI
from .config import Settings
from .models import (
    Chat,
    ChatCreate,
    ChatList,
    ChatReply,
    ClearResult,
    Health,
    MessageCreate,
    Trace,
    TraceList,
)
from .store import TraceNotFound, TraceStore, utc_now

NOT_FOUND = "Not found"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = TraceStore(settings.data_file, settings.max_traces)
    ai = StubAI.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await store.load()
        yield

    app = FastAPI(
        title="AI Chat Trace API",
        version="1.0.0",
        description="Captures chat input and AI response for every turn in memory.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.settings = settings
    app.state.ai = ai

    def get_store(request: Request) -> TraceStore:
        return request.app.state.store

    @app.middleware("http")
    async def _ensure_loaded(request: Request, call_next):
        await store.ensure_loaded()
        return await call_next(request)

    @app.exception_handler(TraceNotFound)
    async def _not_found_handler(request: Request, exc: TraceNotFound):
        return JSONResponse(status_code=404, content={"detail": NOT_FOUND, "id": exc.args[0]})

    @app.get("/health", response_model=Health)
    async def health(store: TraceStore = Depends(get_store)) -> Health:
        chats, traces = await store.stats()
        return Health(
            status="ok",
            chats=chats,
            traces=traces,
            max_traces=store.max_traces,
            persistence=store.data_file is not None,
        )

    @app.post("/api/v1/chats", response_model=Chat, status_code=201)
    async def create_chat(payload: ChatCreate | None = None, store: TraceStore = Depends(get_store)) -> Chat:
        return Chat(**await store.create_chat(payload.title if payload else None))

    @app.get("/api/v1/chats", response_model=ChatList)
    async def list_chats(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        store: TraceStore = Depends(get_store),
    ) -> ChatList:
        items, total = await store.list_chats(limit, offset)
        return ChatList(items=[Chat(**c) for c in items], total=total)

    @app.get("/api/v1/chats/{chat_id}", response_model=Chat)
    async def get_chat(chat_id: str, store: TraceStore = Depends(get_store)) -> Chat:
        return Chat(**await store.get_chat(chat_id))

    @app.delete("/api/v1/chats/{chat_id}", response_model=ClearResult)
    async def delete_chat(chat_id: str, store: TraceStore = Depends(get_store)) -> ClearResult:
        chats, traces = await store.delete_chat(chat_id)
        return ClearResult(deleted_chats=chats, deleted_traces=traces)

    @app.post("/api/v1/chats/{chat_id}/messages", response_model=ChatReply, status_code=201)
    async def send_message(
        chat_id: str,
        payload: MessageCreate,
        request: Request,
        store: TraceStore = Depends(get_store),
    ) -> ChatReply:
        chat = await store.get_chat(chat_id)
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="content must not be blank")
        history_items, _ = await store.list_traces(chat_id, limit=10_000, offset=0)
        history = [t["input"]["content"] for t in reversed(history_items)]

        reply, meta = await request.app.state.ai.reply(content, history)
        trace = await store.add_trace(
            chat_id,
            request_payload={"role": "user", "content": content, "received_at": utc_now()},
            output={"content": reply, **meta},
        )
        return ChatReply(**{"chat": await store.get_chat(chat_id), "message": trace})

    @app.get("/api/v1/chats/{chat_id}/messages", response_model=TraceList)
    async def list_messages(
        chat_id: str,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        store: TraceStore = Depends(get_store),
    ) -> TraceList:
        items, total = await store.list_traces(chat_id, limit, offset)
        return TraceList(items=[Trace(**t) for t in items], total=total)

    @app.get("/api/v1/traces", response_model=TraceList)
    async def list_traces(
        chat_id: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        store: TraceStore = Depends(get_store),
    ) -> TraceList:
        items, total = await store.list_traces(chat_id, limit, offset)
        return TraceList(items=[Trace(**t) for t in items], total=total)

    @app.get("/api/v1/traces/{trace_id}", response_model=Trace)
    async def get_trace(trace_id: str, store: TraceStore = Depends(get_store)) -> Trace:
        return Trace(**await store.get_trace(trace_id))

    @app.delete("/api/v1/traces", response_model=ClearResult)
    async def clear_traces(store: TraceStore = Depends(get_store)) -> ClearResult:
        chats, traces = await store.clear()
        return ClearResult(deleted_chats=chats, deleted_traces=traces)

    return app


app = create_app()
