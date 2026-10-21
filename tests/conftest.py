from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from inswa.config import Settings
from inswa.mock_mcp_server import build_server
from inswa.runtime import create_runtime
from tests.fakes import FakeChatClient

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def mcp_url() -> str:
    port = _free_port()
    app = build_server("127.0.0.1", port).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def make_settings(tmp_path: Path, mcp_url: str = "http://127.0.0.1:1/mcp", **overrides) -> Settings:
    """Settings isolated from the developer's .env file."""
    data = {
        "foundry": {
            "project_endpoint": "https://example.services.ai.azure.com/api/projects/p",
            "default_model": "m",
        },
        "agents": {"definitions_dir": ROOT / "agents"},
        "mcp": {"url": mcp_url},
        "cosmos": {"local_path": tmp_path / "cosmos"},
        "search": {"local_corpus": ROOT / "data" / "search_corpus.json"},
        "telemetry": {"exporter": "none"},
    }
    for key, value in overrides.items():
        data[key] = {**data.get(key, {}), **value} if isinstance(value, dict) else value
    return Settings(_env_file=None, **data)


@pytest.fixture
def settings(tmp_path, mcp_url) -> Settings:
    return make_settings(tmp_path, mcp_url)


@pytest.fixture
async def runtime(settings):
    rt = await create_runtime(settings, chat_client_factory=FakeChatClient)
    yield rt
    await rt.aclose()
