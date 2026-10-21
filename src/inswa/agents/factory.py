"""Builds runnable agents from YAML specs and settings.

Specialists are either in-process `Agent`s (Foundry model + MCP tools) or proxies to
separately deployed Foundry hosted agents, depending on AGENTS__<ROLE>__TRANSPORT.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_framework import Agent, SupportsAgentRun

from inswa.agents.registry import AgentRegistry
from inswa.agents.spec import AgentSpec
from inswa.config import Settings
from inswa.infra.foundry import create_chat_client, create_remote_hosted_agent
from inswa.infra.secrets import SecretProvider
from inswa.tools.mcp import create_mcp_tool

ChatClientFactory = Callable[[str], Any]


class AgentFactory:
    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        *,
        credential: Any,
        secrets: SecretProvider,
        chat_client_factory: ChatClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._credential = credential
        self._secrets = secrets
        self._chat_client_factory = chat_client_factory or (
            lambda role: create_chat_client(settings, role, credential)
        )

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    async def build_local_agent(self, spec: AgentSpec) -> Agent:
        """An in-process Agent Framework agent for `spec` (what a hosted container serves)."""
        tools = []
        if spec.metadata.mcp_tools:
            tools.append(
                await create_mcp_tool(
                    self._settings,
                    name=f"{spec.name}-tools",
                    allowed_tools=spec.metadata.mcp_tools,
                    secrets=self._secrets,
                )
            )
        return Agent(
            client=self._chat_client_factory(spec.role),
            id=spec.name,
            name=spec.name,
            description=spec.description,
            instructions=spec.instructions,
            tools=tools or None,
            default_options=dict(spec.model.options) or None,
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
        """Tool-less agent on the orchestrator's model, used for the intent and compose steps."""
        spec = self._registry.orchestrator
        return Agent(
            client=self._chat_client_factory(spec.role),
            name=f"{spec.name}-{step}",
            instructions=f"{spec.instructions}\n\n{step_instructions}",
            default_options=dict(spec.model.options) or None,
        )
