"""Runs the real Foundry hosting server (Responses protocol) in a subprocess."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.conftest import _free_port

HARNESS = Path(__file__).with_name("hosting_harness.py")


@pytest.fixture
def host(tmp_path, mcp_url):
    procs = []

    def start(agent: str) -> str:
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, str(HARNESS), agent, str(port), mcp_url, str(tmp_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/readiness", timeout=1)
                return base
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.2)
        raise RuntimeError("Hosted agent server did not start")

    yield start
    for proc in procs:
        proc.terminate()
        proc.wait(timeout=10)


def _post(base: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/responses", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def _text(response: dict) -> str:
    return " ".join(
        c.get("text", "")
        for o in response.get("output", [])
        for c in o.get("content", [])
        if isinstance(c, dict)
    )


def test_hosted_orchestrator_follow_up_conversation(host):
    base = host("orchestrator")
    first = _post(base, {"input": "What is the demand forecast for SKU ABC-123 for Contoso?", "store": True})
    assert first["status"] == "completed"
    assert "geography and time period" in _text(first)

    second = _post(base, {"input": "EMEA, Q3 2026", "previous_response_id": first["id"], "store": True})
    assert second["status"] == "completed"
    assert "[E1]" in _text(second)


def test_hosted_specialist_calls_mcp_tool(host):
    base = host("forecasting")
    params = "- geography: EMEA\n- time_period: Q3 2026\n- customer: Contoso\n- sku: ABC-123"
    response = _post(base, {"input": f"Forecast please.\n\nParameters:\n{params}"})
    assert response["status"] == "completed"
    assert "mock-ensemble-v1" in _text(response)
