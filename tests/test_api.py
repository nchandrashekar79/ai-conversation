from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client(**overrides) -> TestClient:
    settings = Settings(**{"data_file": None, "max_traces": 1000, "stub_model": "stub-echo-1", "stub_latency_ms": 0.0, **overrides})
    return TestClient(create_app(settings))


@pytest.fixture
def client() -> TestClient:
    return make_client()


def test_health_reports_empty_store(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body == {"status": "ok", "chats": 0, "traces": 0, "max_traces": 1000, "persistence": False}


def test_create_and_get_chat(client: TestClient) -> None:
    created = client.post("/api/v1/chats", json={"title": "Demo"}).json()
    assert created["title"] == "Demo"
    assert created["message_count"] == 0

    fetched = client.get(f"/api/v1/chats/{created['id']}").json()
    assert fetched == created


def test_create_chat_without_body_defaults_title(client: TestClient) -> None:
    created = client.post("/api/v1/chats").json()
    assert created["title"] == "Untitled chat"


def test_send_message_captures_input_and_output(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats", json={"title": "Trace"}).json()["id"]

    response = client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "hello world"})
    assert response.status_code == 201
    body = response.json()

    trace = body["message"]
    assert trace["input"]["content"] == "hello world"
    assert trace["input"]["role"] == "user"
    assert trace["output"]["content"] == "[stub-echo-1] You said: hello world"
    assert trace["output"]["model"] == "stub-echo-1"
    assert trace["output"]["latency_ms"] >= 0
    assert body["chat"]["message_count"] == 1

    stored = client.get(f"/api/v1/traces/{trace['id']}").json()
    assert stored == trace


def test_messages_include_history_context(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats").json()["id"]
    client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "first"})
    second = client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "second"}).json()
    assert "1 earlier turn(s)" in second["message"]["output"]["content"]


def test_list_messages_newest_first(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats").json()["id"]
    for text in ("a", "b", "c"):
        client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": text})

    listing = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    assert listing["total"] == 3
    assert [t["input"]["content"] for t in listing["items"]] == ["c", "b", "a"]


def test_list_all_traces_filters_by_chat(client: TestClient) -> None:
    first = client.post("/api/v1/chats").json()["id"]
    second = client.post("/api/v1/chats").json()["id"]
    client.post(f"/api/v1/chats/{first}/messages", json={"content": "one"})
    client.post(f"/api/v1/chats/{second}/messages", json={"content": "two"})

    assert client.get("/api/v1/traces").json()["total"] == 2
    filtered = client.get("/api/v1/traces", params={"chat_id": first}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["input"]["content"] == "one"


def test_chat_list_pagination(client: TestClient) -> None:
    for i in range(3):
        client.post("/api/v1/chats", json={"title": f"chat-{i}"})

    page = client.get("/api/v1/chats", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert [c["title"] for c in page["items"]] == ["chat-2", "chat-1"]


def test_delete_chat_removes_traces(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats").json()["id"]
    client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "bye"})

    result = client.delete(f"/api/v1/chats/{chat_id}").json()
    assert result == {"deleted_chats": 1, "deleted_traces": 1}
    assert client.get("/api/v1/traces").json()["total"] == 0
    assert client.get(f"/api/v1/chats/{chat_id}").status_code == 404


def test_clear_traces(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats").json()["id"]
    client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "x"})

    assert client.delete("/api/v1/traces").json() == {"deleted_chats": 1, "deleted_traces": 1}
    assert client.get("/health").json()["chats"] == 0


def test_unknown_ids_return_404(client: TestClient) -> None:
    assert client.get("/api/v1/chats/missing").status_code == 404
    assert client.get("/api/v1/traces/missing").status_code == 404
    assert client.delete("/api/v1/chats/missing").status_code == 404
    assert client.post("/api/v1/chats/missing/messages", json={"content": "hi"}).status_code == 404
    assert client.get("/api/v1/traces", params={"chat_id": "missing"}).status_code == 404


def test_validation_errors(client: TestClient) -> None:
    chat_id = client.post("/api/v1/chats").json()["id"]
    assert client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": ""}).status_code == 422
    assert client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "   "}).status_code == 400
    assert client.post(f"/api/v1/chats/{chat_id}/messages", json={}).status_code == 422


def test_max_traces_evicts_oldest_chat() -> None:
    client = make_client(max_traces=2)
    oldest = client.post("/api/v1/chats", json={"title": "oldest"}).json()["id"]
    client.post(f"/api/v1/chats/{oldest}/messages", json={"content": "1"})
    newer = client.post("/api/v1/chats", json={"title": "newer"}).json()["id"]
    client.post(f"/api/v1/chats/{newer}/messages", json={"content": "2"})
    newest = client.post("/api/v1/chats", json={"title": "newest"}).json()["id"]
    client.post(f"/api/v1/chats/{newest}/messages", json={"content": "3"})

    assert client.get("/health").json()["traces"] == 2
    assert client.get(f"/api/v1/chats/{oldest}").status_code == 404
    assert client.get(f"/api/v1/chats/{newest}").status_code == 200


def test_persistence_round_trip(tmp_path) -> None:
    data_file = tmp_path / "traces.json"

    with make_client(data_file=str(data_file)) as client:
        chat_id = client.post("/api/v1/chats", json={"title": "persisted"}).json()["id"]
        trace = client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "keep me"}).json()["message"]

    snapshot = json.loads(data_file.read_text(encoding="utf-8"))
    assert snapshot["chats"][0]["id"] == chat_id
    assert snapshot["traces"][0]["id"] == trace["id"]

    with make_client(data_file=str(data_file)) as reopened:
        assert reopened.get("/health").json() == {
            "status": "ok",
            "chats": 1,
            "traces": 1,
            "max_traces": 1000,
            "persistence": True,
        }
        assert reopened.get(f"/api/v1/traces/{trace['id']}").json() == trace
