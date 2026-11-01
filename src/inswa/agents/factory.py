"""Builds runnable agents from YAML specs and settings.

Specialists are either in-process `Agent`s (Foundry model + MCP tools) or proxies to
separately deployed Foundry hosted agents, depending on AGENTS__<ROLE>__TRANSPORT.
Agents are cheap and built per request; chat clients are shared per model role.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from agent_framework import Agent, SupportsAgentRun

from inswa.agents.registry import AgentRegistry
from inswa.agents.spec import AgentSpec
from inswa.config import Settings
from inswa.infra.foundry import create_chat_client, create_remote_hosted_agent, default_model_options
from inswa.tools.mcp import create_mcp_tool

ChatClientFactory = Callable[[str], Any]

# Model role of the orchestrator's intent step: a light, fast model (e.g. GPT-5.4-mini).
ROUTER_ROLE = "router"


class AgentFactory:
    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        *,
        credential: Any,
        chat_client_factory: ChatClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._credential = credential
        self._chat_client_factory = chat_client_factory or (
            lambda role: create_chat_client(settings, role, credential)
        )
        self._clients: dict[str, Any] = {}

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    def _client(self, model_role: str) -> Any:
        if model_role not in self._clients:
            self._clients[model_role] = self._chat_client_factory(model_role)
        return self._clients[model_role]

    def _options(self, model_role: str, spec: AgentSpec) -> dict[str, Any] | None:
        return {**default_model_options(self._settings, model_role), **spec.model.options} or None

    async def build_local_agent(self, spec: AgentSpec) -> Agent:
        """An in-process Agent Framework agent for `spec` (what a hosted container serves)."""
        tools = []
        if spec.metadata.mcp_tools:
            tools.append(
                await create_mcp_tool(
                    self._settings,
                    name=f"{spec.name}-tools",
                    allowed_tools=spec.metadata.mcp_tools,
                    credential=self._credential,
                )
            )
        return Agent(
            client=self._client(spec.role),
            id=spec.name,
            name=spec.name,
            description=spec.description,
            instructions=spec.instructions,
            tools=tools or None,
            default_options=self._options(spec.role, spec),
        )

    async def build_specialist(self, role: str) -> SupportsAgentRun:
        """The specialist as the orchestrator should call it: in-process or remote hosted."""
        if not self._registry.is_enabled(role):
            raise ValueError(f"Agent '{role}' is disabled (AGENTS__{role.upper()}__ENABLED=false).")
        spec = self._registry.spec(role)
        if self._settings.agents.toggle(role).transport == "hosted":
            return create_remote_hosted_agent(
                self._settings,
                role,
                self._credential,
                default_name=spec.metadata.hosted_name,
                description=spec.description,
            )
        return await self.build_local_agent(spec)

    def build_orchestrator_step_agent(self, step: str, step_instructions: str) -> Agent:
        """Tool-less agent for an orchestrator step: `intent` runs on the router model, the rest on
        the orchestrator (reasoning) model."""
        spec = self._registry.orchestrator
        model_role = ROUTER_ROLE if step == "intent" else spec.role
        return Agent(
            client=self._client(model_role),
            name=f"{spec.name}-{step}",
            instructions=f"{spec.instructions}\n\n{step_instructions}",
            default_options=self._options(model_role, spec),
        )

    async def aclose(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        await asyncio.gather(*(c.close() for c in clients if hasattr(c, "close")), return_exceptions=True)
