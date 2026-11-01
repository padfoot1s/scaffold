import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from inswa.config import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "inswa"


def test_nested_env_parsing(monkeypatch):
    monkeypatch.setenv("COSMOS__PROVIDER", "cosmos")
    monkeypatch.setenv("FOUNDRY__MODELS__FORECASTING", "gpt-forecast")
    monkeypatch.setenv("FOUNDRY__DEFAULT_MODEL", "gpt-default")
    monkeypatch.setenv("AGENTS__MARKET_TREND__ENABLED", "true")
    s = Settings(_env_file=None)
    assert s.cosmos.provider == "cosmos"
    assert s.foundry.model_for("forecasting") == "gpt-forecast"
    assert s.foundry.model_for("orchestrator") == "gpt-default"
    assert s.agents.market_trend.enabled is True


def test_router_and_reasoning_models_with_providers(monkeypatch):
    monkeypatch.setenv("FOUNDRY__DEFAULT_MODEL", "claude-reasoning")
    monkeypatch.setenv("FOUNDRY__DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setenv("FOUNDRY__MODELS__ROUTER", "gpt-router")
    monkeypatch.setenv("FOUNDRY__PROVIDERS__ROUTER", "openai")
    s = Settings(_env_file=None)
    assert (s.foundry.model_for("router"), s.foundry.provider_for("router")) == ("gpt-router", "openai")
    assert (s.foundry.model_for("rca"), s.foundry.provider_for("rca")) == ("claude-reasoning", "anthropic")


def test_claude_endpoint_derived_from_project_endpoint():
    s = Settings(
        _env_file=None, foundry={"project_endpoint": "https://acct.services.ai.azure.com/api/projects/p"}
    )
    assert s.foundry.resolved_anthropic_base_url() == "https://acct.services.ai.azure.com/anthropic/"
    s.foundry.anthropic_base_url = "https://other.example/anthropic/"
    assert s.foundry.resolved_anthropic_base_url() == "https://other.example/anthropic/"


def test_hosted_runtime_variables_fill_defaults(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://hosted/api/projects/p")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "hosted-model")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    s = Settings(_env_file=None)
    assert s.foundry.project_endpoint == "https://hosted/api/projects/p"
    assert s.foundry.model_for("variance_analysis") == "hosted-model"
    assert s.telemetry.appinsights_connection_string == "InstrumentationKey=abc"


def test_default_flags_and_grain():
    s = Settings(_env_file=None)
    assert s.agents.forecasting.enabled and s.agents.rca.enabled and s.agents.market_recommendations.enabled
    assert not s.agents.market_trend.enabled
    assert s.orchestration.required_slots == ["sku", "primary_customer", "week"]


def test_missing_model_is_reported():
    with pytest.raises(ValueError, match="FOUNDRY__MODELS__ORCHESTRATOR"):
        Settings(_env_file=None).foundry.model_for("orchestrator")


def test_entra_mcp_auth_requires_scope():
    with pytest.raises(ValidationError, match="MCP__SCOPE"):
        Settings(_env_file=None, mcp={"auth": "entra"})


def test_deployment_problems_flag_local_stand_ins():
    problems = " ".join(Settings(_env_file=None).deployment_problems())
    for expected in (
        "managed_identity",
        "COSMOS__PROVIDER",
        "MCP__URL",
        "MCP__AUTH",
        "FOUNDRY__PROJECT_ENDPOINT",
    ):
        assert expected in problems


def test_deployable_configuration_has_no_problems():
    s = Settings(
        _env_file=None,
        azure={"credential": "managed_identity"},
        foundry={"project_endpoint": "https://a.services.ai.azure.com/api/projects/p", "default_model": "m"},
        cosmos={"provider": "cosmos", "endpoint": "https://c.documents.azure.com"},
        mcp={
            "url": "https://mcp.example.azurecontainerapps.io/mcp",
            "auth": "entra",
            "scope": "api://x/.default",
        },
        telemetry={"exporter": "appinsights", "appinsights_connection_string": "InstrumentationKey=abc"},
    )
    assert s.deployment_problems() == []


def test_only_settings_module_reads_environment():
    pattern = re.compile(r"os\.environ|os\.getenv|getenv\(|load_dotenv")
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p.name != "settings.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
