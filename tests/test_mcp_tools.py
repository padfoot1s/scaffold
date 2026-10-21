import json

from inswa.tools.mcp import create_mcp_tool
from tests.conftest import make_settings


async def test_mcp_client_calls_mock_forecast_tool(tmp_path, mcp_url):
    tool = await create_mcp_tool(make_settings(tmp_path, mcp_url), name="t", allowed_tools=["get_forecast"])
    async with tool:
        names = [f.name for f in tool.functions]
        assert names == ["get_forecast"]
        result = await tool.functions[0].invoke(
            arguments={"geography": "EMEA", "time_period": "Q3 2026", "customer": "Contoso", "sku": "123"}
        )
    payload = json.loads(result) if isinstance(result, str) else result
    assert "series" in json.dumps(payload, default=str)
