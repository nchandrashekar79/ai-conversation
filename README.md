# ai-trace — in-memory AI chat trace API

LLM APIs are stateless, so the backend is the bridge that must log the conversation. This
service intercepts every chat prompt and AI reply, records both in memory, and exposes them
over a small REST API.

- **FastAPI + uvicorn** backend
- **Built-in deterministic stub AI** — runs with no API key and no network calls
- **In-memory storage** with optional JSON snapshot persistence
- API only (no web UI)

## Run

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Interactive OpenAPI docs: <http://127.0.0.1:8000/docs>

### Quick start

```powershell
# create a conversation
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/chats -H "Content-Type: application/json" -d "{\"title\":\"Demo\"}"

# send a prompt (input + AI response are recorded as a trace)
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/chats/<CHAT_ID>/messages -H "Content-Type: application/json" -d "{\"content\":\"hello\"}"

# read the captured traces
curl.exe -s http://127.0.0.1:8000/api/v1/traces
```

## REST API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Status plus chat/trace counts and whether persistence is on |
| `POST` | `/api/v1/chats` | Create a chat. Body optional: `{"title": "..."}` |
| `GET` | `/api/v1/chats` | List chats, newest first (`limit`, `offset`) |
| `GET` | `/api/v1/chats/{chat_id}` | Get one chat |
| `DELETE` | `/api/v1/chats/{chat_id}` | Delete a chat and its traces |
| `POST` | `/api/v1/chats/{chat_id}/messages` | Send `{"content": "..."}`; returns the chat and the recorded trace |
| `GET` | `/api/v1/chats/{chat_id}/messages` | List that chat's traces, newest first |
| `GET` | `/api/v1/traces` | List all traces (`chat_id`, `limit`, `offset`) |
| `GET` | `/api/v1/traces/{trace_id}` | Get a single trace |
| `DELETE` | `/api/v1/traces` | Clear all chats and traces |

### Trace shape

Each trace captures both sides of the exchange:

```json
{
  "id": "a0e72aba…",
  "chat_id": "25a3535b…",
  "role": "assistant",
  "input":  { "role": "user", "content": "hello", "received_at": "…" },
  "output": { "content": "[stub-echo-1] You said: hello", "model": "stub-echo-1", "latency_ms": 0.036 },
  "created_at": "…"
}
```

### Errors

- `404` — unknown chat or trace id
- `422` — schema validation failure (missing/oversized content)
- `400` — content is whitespace only

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `AI_TRACE_DATA_FILE` | unset (memory only) | Path to a JSON snapshot. Loaded at startup and written atomically after each change |
| `AI_TRACE_MAX_TRACES` | `1000` | Trace cap; the oldest chat (and its traces) is evicted when exceeded |
| `AI_TRACE_STUB_MODEL` | `stub-echo-1` | Model name reported in trace output |
| `AI_TRACE_STUB_LATENCY_MS` | `0` | Artificial stub latency, useful for testing slow paths |

## Tests

```powershell
python -m pytest tests -q
```

## Notes

- No authentication — intended for local development and demos.
- The stub AI replies deterministically; swapping in a real provider means replacing
  `StubAI.reply()` in `app/ai.py` (traces then record the real model name and latency).
