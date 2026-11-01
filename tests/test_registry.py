import pytest

from inswa.agents.registry import AgentRegistry
from inswa.config import SPECIALIST_ROLES
from tests.conftest import make_settings


def test_specs_load_and_default_flags(tmp_path):
    registry = AgentRegistry.load(make_settings(tmp_path))
    assert registry.orchestrator.prompt("follow_up")
    assert [s.role for s in registry.specialists()] == [
        "forecasting",
        "variance_analysis",
        "statistical_explainability",
        "rca",
        "market_recommendations",
    ]
    assert len(registry.specialists(enabled_only=False)) == 6


def test_route_separates_disabled_agents(tmp_path):
    registry = AgentRegistry.load(make_settings(tmp_path))
    route = registry.route(["forecast", "market_trend", "weather"])
    assert route.enabled_roles == ["forecasting"]
    assert route.disabled_roles == ["market_trend"]
    assert route.unknown_intents == ["weather"]


def test_root_cause_pulls_in_its_upstream_chain_in_stages(tmp_path):
    route = AgentRegistry.load(make_settings(tmp_path)).route(["recommendation"])
    assert route.stages == [
        ["variance_analysis", "statistical_explainability"],
        ["rca"],
        ["market_recommendations"],
    ]


def test_disabled_upstream_is_reported_and_skipped(tmp_path):
    settings = make_settings(tmp_path, agents={"variance_analysis": {"enabled": False}})
    route = AgentRegistry.load(settings).route(["root_cause"])
    assert route.disabled_roles == ["variance_analysis"]
    assert route.stages == [["statistical_explainability"], ["rca"]]


def test_flag_enables_agent(tmp_path):
    settings = make_settings(tmp_path, agents={"market_trend": {"enabled": True}})
    registry = AgentRegistry.load(settings)
    assert registry.route(["market_trend"]).enabled_roles == ["market_trend"]


def test_dependency_cycle_is_rejected(tmp_path):
    registry = AgentRegistry.load(make_settings(tmp_path))
    specs = {r: registry.spec(r) for r in ("orchestrator", *SPECIALIST_ROLES)}
    specs["variance_analysis"] = specs["variance_analysis"].model_copy(deep=True)
    specs["variance_analysis"].metadata.requires = ["rca"]
    with pytest.raises(ValueError, match="cycle"):
        AgentRegistry(make_settings(tmp_path), specs)
