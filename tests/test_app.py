from __future__ import annotations

from backend.agent.schema import DoneEvent, TokenEvent
from backend.app import app
from backend.store import ConversationStore
from fastapi.testclient import TestClient


def _isolate_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.store", ConversationStore(tmp_path / "agent.db"))


def test_health() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


def test_cookies_status_has_no_secret_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COOKIES_DIR", str(tmp_path))
    from backend.skills.cookies import CookieJar

    CookieJar(root=tmp_path).save_storage_state(
        "zhihu",
        {"cookies": [{"name": "z_c0", "value": "SUPER_SECRET", "domain": ".zhihu.com", "path": "/"}], "origins": []},
    )
    with TestClient(app) as client:
        payload = client.get("/api/cookies").json()
    blob = str(payload)
    assert "SUPER_SECRET" not in blob
    zhihu = next(item for item in payload["platforms"] if item["platform"] == "zhihu")
    assert zhihu["configured"] is True


def test_list_skills_includes_unavailable_extras() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/skills").json()
    names = [item["name"] for item in payload["skills"]]
    assert "search_web" in names
    assert "scrape_rendered" in names
    rendered = next(item for item in payload["skills"] if item["name"] == "scrape_rendered")
    if not rendered["available"]:
        assert "crawl4ai" in (rendered["install_cmd"] or "")



def test_list_skills() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/skills").json()
    names = [item["name"] for item in payload["skills"]]
    assert "search_web" in names
    assert "scrape_page" in names
    assert "scrape_rendered" in names
    search = next(item for item in payload["skills"] if item["name"] == "search_web")
    assert search["available"] is True



def test_chat_sse_events(monkeypatch, tmp_path) -> None:
    _isolate_store(monkeypatch, tmp_path)

    async def fake_run(*_args, **_kwargs):
        yield TokenEvent(request_id="x", text="hi")
        yield DoneEvent(request_id="x", status="complete")

    monkeypatch.setattr("backend.app.run_agent", fake_run)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat", json={"message": "hello"}) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
    assert "event: token" in body
    assert '"text":"hi"' in body or '"text": "hi"' in body
    assert "event: done" in body


def test_chat_sse_waits_past_one_second(monkeypatch, tmp_path) -> None:
    _isolate_store(monkeypatch, tmp_path)

    async def slow_run(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(1.2)
        yield TokenEvent(request_id="x", text="hi")
        yield DoneEvent(request_id="x", status="complete")

    monkeypatch.setattr("backend.app.run_agent", slow_run)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat", json={"message": "hello"}) as response:
            body = "".join(response.iter_text())
    assert "event: token" in body
    assert '"status":"complete"' in body or '"status": "complete"' in body


def test_chat_sse_ignores_false_disconnect_before_agent_output(monkeypatch, tmp_path) -> None:
    _isolate_store(monkeypatch, tmp_path)

    async def slow_run(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(1.2)
        yield TokenEvent(request_id="x", text="hi")
        yield DoneEvent(request_id="x", status="complete")

    async def always_disconnected(_self) -> bool:
        return True

    monkeypatch.setattr("backend.app.run_agent", slow_run)
    monkeypatch.setattr("starlette.requests.Request.is_disconnected", always_disconnected)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat", json={"message": "hello"}) as response:
            body = "".join(response.iter_text())
    assert "event: token" in body
    assert '"status":"complete"' in body or '"status": "complete"' in body
