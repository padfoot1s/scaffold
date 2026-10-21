from inswa.agents.registry import AgentRegistry
from tests.conftest import make_settings


def test_specs_load_and_default_flags(tmp_path):
    registry = AgentRegistry.load(make_settings(tmp_path))
    assert registry.orchestrator.prompt("follow_up")
    assert [s.role for s in registry.specialists()] == [
        "forecasting",
        "variance_analysis",
        "statistical_explainability",
    ]
    assert len(registry.specialists(enabled_only=False)) == 6


def test_route_separates_disabled_agents(tmp_path):
    registry = AgentRegistry.load(make_settings(tmp_path))
    route = registry.route(["forecast", "root_cause", "weather"])
    assert route.enabled_roles == ["forecasting"]
    assert route.disabled_roles == ["rca"]
    assert route.unknown_intents == ["weather"]


def test_flag_enables_agent(tmp_path):
    settings = make_settings(tmp_path, agents={"market_trend": {"enabled": True}})
    registry = AgentRegistry.load(settings)
    assert registry.route(["market_trend"]).enabled_roles == ["market_trend"]
