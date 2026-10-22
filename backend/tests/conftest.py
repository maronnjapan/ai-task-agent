from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AIWM_ENV_FILE", "/nonexistent/.env")

from app.config import Settings  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.infrastructure.secrets.base import InMemorySecretProvider  # noqa: E402
from app.llm.fake import ScriptedChatModel  # noqa: E402
from app.main import build_context, create_app  # noqa: E402
from app.platform.linux import LinuxPlatformAdapter  # noqa: E402

CSRF = {"X-Requested-With": "AIWM"}


class FakeRunner:
    """Records subprocess invocations for platform adapter tests."""

    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.responses: dict[str, tuple[int, str]] = {}

    def __call__(self, args: list[str], input_text: str | None = None):
        import subprocess

        self.calls.append(list(args))
        for key, (code, out) in self.responses.items():
            if key in " ".join(args):
                return subprocess.CompletedProcess(args, code, out, "")
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(
        aiwm_data_dir=str(data_dir),
        aiwm_disable_orchestrator=True,
        aiwm_llm_provider_override="fake",
        manager_model="scripted",
        worker_model="scripted",
        review_model="scripted",
        secret_backend="dotenv",
        enable_desktop_notifications=False,
        max_replanning_attempts=2,
        max_worker_retries=1,
        max_consecutive_no_progress=2,
    )


@pytest.fixture
def platform(tmp_path: Path) -> LinuxPlatformAdapter:
    return LinuxPlatformAdapter(runner=FakeRunner(), home=tmp_path / "home")


@pytest.fixture
def ctx(settings: Settings, platform: LinuxPlatformAdapter) -> Iterator[AppContext]:
    context = build_context(
        settings=settings, platform=platform, secret_store=InMemorySecretProvider(), use_migrations=False
    )
    yield context
    context.db.dispose()


def make_test_client(ctx: AppContext, with_session: bool = True) -> TestClient:
    """TestClient for ``ctx``: allows the ``testserver`` Host and opens the tokenised URL for a session cookie."""
    from app.main import session_token

    app = create_app(ctx, serve_frontend=False, extra_hosts={"testserver"})
    test_client = TestClient(app)
    test_client.headers.update(CSRF)
    if with_session:
        token = session_token(ctx)
        if token:
            test_client.get("/", params={"token": token})
    return test_client


@pytest.fixture
def client(ctx: AppContext) -> Iterator[TestClient]:
    with make_test_client(ctx) as test_client:
        yield test_client


@pytest.fixture
def models(ctx: AppContext) -> dict[str, ScriptedChatModel]:
    """Scripted models wired into the LLM factory for manager / worker / review."""
    result = {}
    for agent in ("manager", "worker", "review"):
        model = ScriptedChatModel(model_name=f"scripted-{agent}")
        ctx.llm_factory.set_shared_model(agent, model)
        result[agent] = model
    return result


def tool_call(name: str, **args):
    return {"tool_calls": [{"name": name, "args": args}]}


def last_tool_json(messages):
    """Parse the JSON content of the most recent ToolMessage."""
    from langchain_core.messages import ToolMessage

    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            try:
                return json.loads(message.content)
            except (TypeError, ValueError):
                return message.content
    return None
