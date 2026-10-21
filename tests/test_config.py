import re
from pathlib import Path

import pytest

from inswa.config import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "inswa"


def test_nested_env_parsing(monkeypatch):
    monkeypatch.setenv("COSMOS__PROVIDER", "cosmos")
    monkeypatch.setenv("FOUNDRY__MODELS__FORECASTING", "gpt-forecast")
    monkeypatch.setenv("FOUNDRY__DEFAULT_MODEL", "gpt-default")
    monkeypatch.setenv("AGENTS__RCA__ENABLED", "true")
    s = Settings(_env_file=None)
    assert s.cosmos.provider == "cosmos"
    assert s.foundry.model_for("forecasting") == "gpt-forecast"
    assert s.foundry.model_for("orchestrator") == "gpt-default"
    assert s.agents.rca.enabled is True


def test_hosted_runtime_variables_fill_defaults(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://hosted/api/projects/p")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "hosted-model")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    s = Settings(_env_file=None)
    assert s.foundry.project_endpoint == "https://hosted/api/projects/p"
    assert s.foundry.model_for("variance_analysis") == "hosted-model"
    assert s.telemetry.appinsights_connection_string == "InstrumentationKey=abc"


def test_disabled_agents_default_off():
    s = Settings(_env_file=None)
    assert not s.agents.rca.enabled
    assert not s.agents.market_trend.enabled
    assert not s.agents.market_recommendations.enabled
    assert s.agents.forecasting.enabled


def test_missing_model_is_reported():
    with pytest.raises(ValueError, match="FOUNDRY__MODELS__ORCHESTRATOR"):
        Settings(_env_file=None).foundry.model_for("orchestrator")


def test_only_settings_module_reads_environment():
    pattern = re.compile(r"os\.environ|os\.getenv|getenv\(|load_dotenv")
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p.name != "settings.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
