from __future__ import annotations

from backend.agent.schema import DoneEvent, ErrorEvent, TokenEvent, ToolEndEvent, ToolStartEvent
from backend.app import app
from backend.models_catalog import MODEL_IDS
from backend.store import ConversationStore
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path) -> TestClient:
    store = ConversationStore(tmp_path / "agent.db")
    monkeypatch.setattr("backend.app.store", store)
    return TestClient(app), store


def test_models_include_minimax_family() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/models").json()
    ids = [item["id"] for item in payload["models"]]
    assert payload["default"] == "MiniMax-M3"
    for model_id in (
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ):
        assert model_id in ids
    assert set(ids) == set(MODEL_IDS)


def test_conversation_crud_and_search(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    created = client.post("/api/conversations", json={"model": "MiniMax-M2.7"}).json()
    assert created["model"] == "MiniMax-M2.7"
    assert created["title"] == "新对话"

    client.patch(f"/api/conversations/{created['id']}", json={"title": "Fastify 升级"})
    listed = client.get("/api/conversations", params={"q": "fastify"}).json()
    assert listed["conversations"][0]["title"] == "Fastify 升级"

    store.add_message(created["id"], "user", "hello")
    detail = client.get(f"/api/conversations/{created['id']}").json()
    assert detail["messages"][0]["content"] == "hello"

    deleted = client.delete(f"/api/conversations/{created['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/conversations/{created['id']}").status_code == 404


def test_chat_persists_and_rejects_unknown_model(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)

    async def fake_run(message, history, **kwargs):
        assert kwargs.get("model") == "MiniMax-M2.7"
        assert history == []
        assert message == "你好"
        yield TokenEvent(request_id="x", text="pong")
        yield DoneEvent(request_id="x", status="complete")

    monkeypatch.setattr("backend.app.run_agent", fake_run)
    unknown = client.post("/api/chat", json={"message": "hi", "model": "gpt-4o-mini"})
    assert unknown.status_code == 400

    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "你好", "model": "MiniMax-M2.7"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: conversation" in body
    assert "event: token" in body
    conversations = store.list_conversations()
    assert len(conversations) == 1
    loaded = store.get_conversation(conversations[0].id)
    assert loaded is not None
    assert loaded.model == "MiniMax-M2.7"
    assert loaded.title == "你好"
    assert [message.content for message in loaded.messages] == ["你好", "pong"]


def test_chat_persists_tool_cards(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)

    async def fake_run(*_args, **_kwargs):
        yield ToolStartEvent(request_id="x", name="search_web", args={"query": "fastify"})
        yield ToolEndEvent(request_id="x", name="search_web", status="ok", preview="3 hits")
        yield TokenEvent(request_id="x", text="ok")
        yield DoneEvent(request_id="x", status="complete")

    monkeypatch.setattr("backend.app.run_agent", fake_run)
    with client.stream("POST", "/api/chat", json={"message": "搜一下"}) as response:
        "".join(response.iter_text())
    loaded = store.get_conversation(store.list_conversations()[0].id)
    assert loaded is not None
    tools = loaded.messages[1].tools
    assert tools[0].name == "search_web"
    assert tools[0].status == "ok"
    assert tools[0].preview == "3 hits"


def test_chat_persists_error_text(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)

    async def fake_run(*_args, **_kwargs):
        yield ErrorEvent(request_id="x", message="Connection error.")
        yield DoneEvent(request_id="x", status="error")

    monkeypatch.setattr("backend.app.run_agent", fake_run)
    with client.stream("POST", "/api/chat", json={"message": "你好"}) as response:
        "".join(response.iter_text())
    loaded = store.get_conversation(store.list_conversations()[0].id)
    assert loaded is not None
    assert loaded.messages[1].content == "Connection error."
