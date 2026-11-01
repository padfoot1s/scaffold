import json
from types import SimpleNamespace

import pytest

import inswa.tools.mcp as mcp_module
from inswa.tools.mcp import create_mcp_tool
from tests.conftest import make_settings

GRAIN = {"sku": "123", "primary_customer": "Contoso", "week": "2026-11-10"}


async def _call(settings, tool_name: str, arguments: dict) -> str:
    tool = await create_mcp_tool(settings, name="t", allowed_tools=[tool_name])
    async with tool:
        assert [f.name for f in tool.functions] == [tool_name]
        result = await tool.functions[0].invoke(arguments=arguments)
    return result if isinstance(result, str) else json.dumps(result, default=str)


async def test_forecast_tool_returns_weekly_grain_with_run_metadata(tmp_path, mcp_url):
    text = await _call(make_settings(tmp_path, mcp_url), "get_forecast", {**GRAIN, "horizon_weeks": 2})
    for field in ("forecast_run_id", "model_version", "as_of", "2026-W46", "2026-W47", "p10", "p90"):
        assert field in text


async def test_variance_is_computed_by_the_tool(tmp_path, mcp_url):
    text = await _call(make_settings(tmp_path, mcp_url), "analyze_variance", GRAIN)
    assert "total_variance_pct" in text and "flagged_weeks" in text


async def test_entra_auth_sends_a_bearer_token_for_the_configured_scope(tmp_path, monkeypatch):
    scopes, built = [], []

    class Credential:
        async def get_token(self, scope):
            scopes.append(scope)
            return SimpleNamespace(token="tok-123")

    monkeypatch.setattr(mcp_module, "MCPStreamableHTTPTool", lambda **kwargs: built.append(kwargs))
    settings = make_settings(tmp_path, mcp={"auth": "entra", "scope": "api://mcp/.default"})
    await create_mcp_tool(settings, name="t", allowed_tools=["get_forecast"], credential=Credential())
    assert scopes == ["api://mcp/.default"]
    assert built[0]["static_headers"] == {"Authorization": "Bearer tok-123"}
    assert built[0]["approval_mode"] == "never_require"


async def test_entra_auth_without_credential_fails(tmp_path):
    settings = make_settings(tmp_path, mcp={"auth": "entra", "scope": "api://mcp/.default"})
    with pytest.raises(ValueError, match="credential"):
        await create_mcp_tool(settings, name="t", allowed_tools=["get_forecast"])
