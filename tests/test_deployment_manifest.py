"""Guards azure.yaml: every hosted agent gets a model setting per agent role."""

import re
from pathlib import Path

import yaml

from inswa.config import AGENT_ROLES, Settings

MANIFEST = yaml.safe_load((Path(__file__).resolve().parents[1] / "azure.yaml").read_text(encoding="utf-8"))
AGENT_SERVICES = {k: v for k, v in MANIFEST["services"].items() if v.get("host") == "azure.ai.agent"}
DEPLOYMENTS = {d["name"] for d in MANIFEST["services"]["ai-project"]["deployments"]}


def _default(value: str) -> str:
    """`${NAME=default}` -> `default`."""
    match = re.fullmatch(r"\$\{\w+=(.*)\}", value)
    return match.group(1) if match else value


def test_every_hosted_agent_gets_every_role_model():
    for name, service in AGENT_SERVICES.items():
        env = service["env"]
        missing = [r for r in AGENT_ROLES if f"FOUNDRY__MODELS__{r.upper()}" not in env]
        assert not missing, f"{name} lacks model settings for {missing}"


def test_enabled_roles_have_their_own_declared_deployment():
    settings = Settings(_env_file=None)
    env = next(iter(AGENT_SERVICES.values()))["env"]
    for role in AGENT_ROLES:
        enabled = role == "orchestrator" or settings.agents.toggle(role).enabled
        model = _default(env[f"FOUNDRY__MODELS__{role.upper()}"])
        if enabled:
            assert model in DEPLOYMENTS, f"{role} -> '{model}' is not a deployment in azure.yaml"
    models = [_default(env[f"FOUNDRY__MODELS__{r.upper()}"]) for r in AGENT_ROLES]
    enabled_models = [m for m in models if m]
    assert len(enabled_models) == len(set(enabled_models)), "roles should not share a deployment by default"
    assert _default(env["AZURE_AI_MODEL_DEPLOYMENT_NAME"]) in DEPLOYMENTS


def test_each_service_hosts_a_distinct_agent():
    hosted = [s["env"]["HOSTING__AGENT"] for s in AGENT_SERVICES.values()]
    expected = ["orchestrator", "forecasting", "variance_analysis", "statistical_explainability"]
    assert sorted(hosted) == sorted(expected)
