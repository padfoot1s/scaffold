"""Guards azure.yaml: hosted agents are deployable, strict, and use the router + reasoning models."""

import re
from pathlib import Path

import yaml

from inswa.config import SPECIALIST_ROLES, Settings

MANIFEST = yaml.safe_load((Path(__file__).resolve().parents[1] / "azure.yaml").read_text(encoding="utf-8"))
AGENT_SERVICES = {k: v for k, v in MANIFEST["services"].items() if v.get("host") == "azure.ai.agent"}
DEPLOYMENTS = {d["name"] for d in MANIFEST["services"]["ai-project"]["deployments"]}


def _default(value: str) -> str | None:
    """`${NAME=default}` -> `default`; `${NAME}` (required) -> None."""
    match = re.fullmatch(r"\$\{\w+(?:=(.*))?\}", str(value))
    return match.group(1) if match else str(value)


def test_router_and_reasoning_defaults_are_declared_deployments():
    for name, service in AGENT_SERVICES.items():
        env = service["env"]
        assert _default(env["FOUNDRY__MODELS__ROUTER"]) in DEPLOYMENTS, name
        assert _default(env["AZURE_AI_MODEL_DEPLOYMENT_NAME"]) in DEPLOYMENTS, name


def test_hosted_agents_are_strict_and_have_no_local_fallbacks():
    for name, service in AGENT_SERVICES.items():
        env = service["env"]
        assert env["HOSTING__STRICT"] == "true", name
        assert env["AZURE__CREDENTIAL"] == "managed_identity", name
        assert env["COSMOS__PROVIDER"] == "cosmos" and env["MCP__AUTH"] == "entra", name
        for required in ("MCP__URL", "MCP__SCOPE", "COSMOS__ENDPOINT"):
            assert _default(env[required]) is None, f"{name}: {required} must not have a default"


def test_each_enabled_agent_is_hosted_once():
    settings = Settings(_env_file=None)
    hosted = [s["env"]["HOSTING__AGENT"] for s in AGENT_SERVICES.values()]
    enabled = ["orchestrator", *(r for r in SPECIALIST_ROLES if settings.agents.toggle(r).enabled)]
    assert sorted(hosted) == sorted(enabled)
