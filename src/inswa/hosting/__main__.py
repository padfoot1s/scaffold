"""Serve one agent over the Foundry Responses protocol: python -m inswa.hosting

HOSTING__AGENT selects the agent. The same image is deployed once per agent in azure.yaml.
Agents are created per request (fresh MCP connections, as recommended for hosted agents).
"""

from __future__ import annotations

import asyncio
import logging

from agent_framework_foundry_hosting import ResponsesHostServer

from inswa.agents.registry import AgentRegistry
from inswa.config import AGENT_ROLES, Settings, get_settings
from inswa.infra.telemetry import setup_telemetry
from inswa.orchestration.agent import OrchestratorAgent
from inswa.runtime import Runtime, create_runtime

# Telemetry is owned by inswa.infra.telemetry (driven by TELEMETRY__* settings), so the hosting
# SDK's own env-driven observability setup is turned off.
_HOST_OPTIONS = {"configure_observability": None}


class _LazyRuntime:
    """Creates the runtime on the server's event loop at the first request."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runtime: Runtime | None = None
        self._lock: asyncio.Lock | None = None

    async def get(self) -> Runtime:
        if self._runtime is None:
            self._lock = self._lock or asyncio.Lock()
            async with self._lock:
                if self._runtime is None:
                    self._runtime = await create_runtime(self._settings)
        return self._runtime


def build_server(settings: Settings) -> ResponsesHostServer:
    role = settings.hosting.agent
    if role not in AGENT_ROLES:
        raise ValueError(f"HOSTING__AGENT must be one of {AGENT_ROLES}, got '{role}'.")
    if settings.hosting.strict and (problems := settings.deployment_problems()):
        raise ValueError(
            "HOSTING__STRICT=true but the configuration is not deployable:\n- " + "\n- ".join(problems)
        )
    registry = AgentRegistry.load(settings)
    if not registry.is_enabled(role):
        raise ValueError(f"Agent '{role}' is disabled; set AGENTS__{role.upper()}__ENABLED=true to host it.")
    runtime = _LazyRuntime(settings)

    if role == "orchestrator":

        async def orchestrator_factory() -> OrchestratorAgent:
            return OrchestratorAgent(await runtime.get())

        # The orchestrator keeps its own conversation memory (Cosmos), keyed by the session id.
        # Being a custom agent (not a RawAgent), it serves stored requests only: the host rejects
        # `store: false` because it cannot guarantee a custom agent stores nothing.
        return ResponsesHostServer(agent=orchestrator_factory, history_source="agent", **_HOST_OPTIONS)

    async def specialist_factory():
        rt = await runtime.get()
        return await rt.factory.build_local_agent(rt.registry.spec(role))

    return ResponsesHostServer(agent=specialist_factory, **_HOST_OPTIONS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    setup_telemetry(settings)
    build_server(settings).run(host=settings.hosting.host, port=settings.hosting.port)


if __name__ == "__main__":
    main()
