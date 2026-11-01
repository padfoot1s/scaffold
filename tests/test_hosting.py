import pytest
from agent_framework_foundry_hosting import ResponsesHostServer

from inswa.hosting.__main__ import build_server
from tests.conftest import make_settings


@pytest.mark.parametrize("agent", ["orchestrator", "forecasting"])
def test_build_server_for_enabled_agents(tmp_path, agent):
    assert isinstance(build_server(make_settings(tmp_path, hosting={"agent": agent})), ResponsesHostServer)


def test_disabled_agent_cannot_be_hosted(tmp_path):
    with pytest.raises(ValueError, match="disabled"):
        build_server(make_settings(tmp_path, hosting={"agent": "market_trend"}))


def test_strict_hosting_refuses_local_stand_ins(tmp_path):
    with pytest.raises(ValueError, match="not deployable") as info:
        build_server(make_settings(tmp_path, hosting={"agent": "orchestrator", "strict": True}))
    assert "COSMOS__PROVIDER" in str(info.value) and "MCP__AUTH" in str(info.value)
