from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.context import AppContext


def test_csrf_and_host_protection(ctx: AppContext):
    from app.main import create_app

    app = create_app(ctx, serve_frontend=False)
    with TestClient(app) as client:
        assert client.post("/api/tasks", json={"title": "x"}).status_code == 403
        assert (
            client.post(
                "/api/tasks",
                json={"title": "x"},
                headers={"X-Requested-With": "AIWM", "Origin": "http://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/tasks",
                json={"title": "x"},
                headers={"X-Requested-With": "AIWM", "Origin": "http://127.0.0.1:8765"},
            ).status_code
            == 201
        )
        assert client.get("/api/tasks", headers={"Host": "evil.example"}).status_code == 400
        assert client.get("/api/tasks").status_code == 200


def test_task_endpoints(client: TestClient):
    cat = client.post("/api/categories", json={"name": "設計"}).json()
    created = client.post(
        "/api/tasks", json={"title": "API タスク", "category_id": cat["id"], "assignee": "ai"}
    ).json()
    assert created["category_name"] == "設計" and created["status"] == "todo"
    listed = client.get("/api/tasks", params={"category_id": cat["id"]}).json()
    assert listed["total"] == 1
    updated = client.patch(
        f"/api/tasks/{created['id']}", json={"description": "詳細", "status": "review_pending"}
    ).json()
    assert updated["status"] == "review_pending"
    history = client.get(f"/api/tasks/{created['id']}/history").json()
    assert [h["version"] for h in history] == [2, 1] and history[0]["previous_content"]["description"] is None
    assert (
        client.post(f"/api/tasks/{created['id']}/revert", json={"version": 1}).json()["description"] is None
    )
    client.patch(f"/api/tasks/{created['id']}", json={"status": "review_pending"})
    assert (
        client.post(f"/api/tasks/{created['id']}/approve", json={"comment": "良い"}).json()["status"]
        == "completed"
    )
    assert client.post(f"/api/tasks/{created['id']}/reopen").json()["status"] == "todo"
    ctx_row = client.post(f"/api/tasks/{created['id']}/contexts", json={"context": "補足情報"}).json()
    assert (
        ctx_row["status"] == "open"
        and client.get(f"/api/tasks/{created['id']}/contexts").json()[0]["id"] == ctx_row["id"]
    )
    assert client.delete(f"/api/tasks/{created['id']}").json()["is_deleted"] is True
    assert client.get("/api/tasks").json()["total"] == 0
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.patch(f"/api/categories/{cat['id']}", json={"name": "設計2"}).json()["name"] == "設計2"
    assert client.delete(f"/api/categories/{cat['id']}").json()["ok"]


def test_chat_decision_memory_endpoints(client: TestClient):
    task = client.post("/api/tasks", json={"title": "chat task"}).json()
    chat = client.post(f"/api/tasks/{task['id']}/chats", json={"title": "相談"}).json()
    msg = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "こんにちは", "reply": False}
    ).json()
    page = client.get(f"/api/chats/{chat['id']}/messages").json()
    assert page["items"][0]["id"] == msg["id"] and not page["has_more"]
    decision = client.post(
        f"/api/tasks/{task['id']}/decisions", json={"content": "方式A", "source_message_id": msg["id"]}
    ).json()
    assert decision["status"] == "active"
    assert client.get(f"/api/tasks/{task['id']}/decisions").json()[0]["id"] == decision["id"]
    assert client.delete(f"/api/decisions/{decision['id']}").json()["status"] == "revoked"
    memory = client.post(
        "/api/memories", json={"scope": "task", "task_id": task["id"], "content": "重要な調査結果メモ"}
    ).json()
    assert client.get("/api/memories", params={"q": "調査結果"}).json()[0]["id"] == memory["id"]
    assert client.patch(f"/api/memories/{memory['id']}", json={"confirmed": True}).json()["confirmed"] is True
    assert client.delete(f"/api/memories/{memory['id']}").json()["ok"]
    assert (
        client.put("/api/user-state", json={"condition": "疲れている", "expires_in_minutes": 30}).json()[
            "active"
        ]
        is True
    )
    assert client.get("/api/user-state").json()["condition"] == "疲れている"
    assert client.get(f"/api/tasks/{task['id']}/chats").json()[0]["message_count"] == 1
    assert client.delete(f"/api/chats/{chat['id']}").json()["ok"]


def test_artifact_endpoints(client: TestClient, ctx: AppContext):
    task = client.post("/api/tasks", json={"title": "artifact task"}).json()
    artifact = client.post(
        "/api/artifacts", json={"task_id": task["id"], "title": "設計書", "content": "# 設計\n\n初版"}
    ).json()
    aid = artifact["id"]
    assert client.get(f"/api/artifacts/{aid}/content").json()["content"].startswith("# 設計")
    client.put(f"/api/artifacts/{aid}/content", json={"content": "# 設計\n\n第二版", "change_note": "更新"})
    versions = client.get(f"/api/artifacts/{aid}/versions").json()
    assert [v["version"] for v in versions] == [1, 2]
    diff = client.get(f"/api/artifacts/{aid}/diff", params={"from": 1, "to": 2}).json()
    assert any(line["type"] == "added" and "第二版" in line["text"] for line in diff["lines"])
    assert client.post(f"/api/artifacts/{aid}/restore", json={"version": 1}).json()["version"] == 3
    assert (
        client.get(f"/api/artifacts/{aid}/content", params={"version": 1}).json()["content"].endswith("初版")
    )
    assert client.post(f"/api/artifacts/{aid}/approve").json()["status"] == "approved"
    assert (
        client.post(f"/api/artifacts/{aid}/revision", json={"instructions": "図を追加"}).json()["status"]
        == "revision_requested"
    )
    assert client.get(f"/api/tasks/{task['id']}/artifacts").json()[0]["id"] == aid
    assert client.get("/api/artifacts", params={"status": "revision_requested"}).json()[0]["id"] == aid
    opened = client.post(f"/api/artifacts/{aid}/open").json()
    assert opened["data"]["path"].endswith("-v3.md")
    exported = client.get(f"/api/artifacts/{aid}/export", params={"format": "html", "save": True})
    assert (
        exported.status_code == 200
        and "<h1>設計</h1>" in exported.text
        and exported.headers["content-type"].startswith("text/html")
    )
    assert list(ctx.paths.exports.glob("*.html"))
    assert (
        client.get(f"/api/artifacts/{aid}/export", params={"format": "text"}).text.strip().startswith("設計")
    )
    assert client.get(f"/api/artifacts/{aid}/export", params={"format": "docx"}).status_code == 400


def test_settings_api_keys_and_system(client: TestClient, ctx: AppContext, tmp_path: Path):
    settings = client.get("/api/settings").json()
    assert settings["llm"]["manager"]["model"] == "scripted" and settings["secret_backend"] == "memory"
    assert not any(k["configured"] for k in settings["api_keys"])
    patched = client.patch(
        "/api/settings",
        json={
            "manager": {**settings["manager"], "autonomy_level": "proactive", "custom_prompt": "公式を優先"},
            "notifications": {**settings["notifications"], "level": "high"},
        },
    ).json()
    assert patched["manager"]["autonomy_level"] == "proactive" and patched["notifications"]["level"] == "high"
    keys = client.post(
        "/api/settings/api-keys", json={"provider": "openai", "api_key": "sk-proj-verysecretkeyvalue"}
    ).json()
    assert next(k for k in keys if k["provider"] == "openai")["configured"]
    assert ctx.secrets.get_secret("OPENAI_API_KEY") == "sk-proj-verysecretkeyvalue"
    assert "sk-proj-verysecretkeyvalue" not in json.dumps(client.get("/api/settings").json())
    keys = client.request("DELETE", "/api/settings/api-keys", json={"provider": "openai"}).json()
    assert not next(k for k in keys if k["provider"] == "openai")["configured"]
    status = client.get("/api/system/status").json()
    assert status["counts"]["tasks"] == 0 and status["platform"]["name"] == "linux"
    backup = client.post("/api/system/backup", json={"label": "api"}).json()
    assert Path(backup["path"]).exists() and "database" in backup["includes"]
    assert client.get("/api/system/backups").json()[0]["path"] == backup["path"]
    assert client.post("/api/system/restore", json={"path": backup["path"]}).status_code == 400
    restored = client.post("/api/system/restore", json={"path": backup["path"], "confirm": True}).json()
    assert Path(restored["safety_backup"]).exists()
    audit = client.get("/api/audit", params={"event_type": "backup.restored"}).json()
    assert audit["total"] == 1
    assert client.post("/api/settings/autostart", json={"enabled": True}).json()["data"]["installed"] is True
    assert (
        client.post("/api/settings/autostart", json={"enabled": False}).json()["data"]["installed"] is False
    )
    assert client.get("/api/manager/status").json()["state"] == "disabled"
    assert client.get("/api/manager/schedule").json() == []
    assert client.get("/api/notifications").json()["unread"] == 0


def test_integrations_crud(client: TestClient, ctx: AppContext):
    presets = {p["adapter"]: p for p in client.get("/api/integrations/presets").json()}
    assert presets["slack"]["command"] == "npx" and presets["jira"]["tool_permissions"]
    body = {
        "name": "local-http",
        "transport": "streamable_http",
        "url": "http://127.0.0.1:1/mcp",
        "auth_type": "bearer",
        "secret": "tok-123",
        "tool_permissions": [{"tool_name": "post_message", "permission": "external_write", "enabled": False}],
    }
    created = client.post("/api/integrations", json=body).json()
    assert created["has_secret"] and created["secret_ref"] and "tok-123" not in json.dumps(created)
    assert ctx.secret_store.get_secret(created["secret_ref"]) == "tok-123"
    assert (
        client.post("/api/integrations", json={**body, "name": "bad", "transport": "stdio"}).status_code
        == 422
    )
    updated = client.patch(
        f"/api/integrations/{created['id']}",
        json={
            "enabled": False,
            "tool_permissions": [{"tool_name": "post_message", "permission": "read", "enabled": True}],
        },
    ).json()
    assert updated["enabled"] is False and updated["tool_permissions"][0]["permission"] == "read"
    assert client.get("/api/integrations").json()[0]["id"] == created["id"]
    test = client.post(f"/api/integrations/{created['id']}/test").json()
    assert test["ok"] is False
    assert client.delete(f"/api/integrations/{created['id']}").json()["ok"]
    assert ctx.secret_store.get_secret(created["secret_ref"]) is None


def test_sse_stream(client: TestClient, ctx: AppContext):
    with client.stream("GET", "/api/system/events") as response:
        assert response.status_code == 200
        lines = []
        ctx.broker.publish("task.created", {"task_id": "abc"})
        for line in response.iter_lines():
            lines.append(line)
            if any("task.created" in item for item in lines) and any("abc" in item for item in lines):
                break
        assert any(line.startswith("event: hello") for line in lines)
