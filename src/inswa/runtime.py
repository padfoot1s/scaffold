"""Process runtime: settings plus every infrastructure adapter, created from config only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from inswa.agents.factory import AgentFactory, ChatClientFactory
from inswa.agents.registry import AgentRegistry
from inswa.config import Settings
from inswa.infra.feedback import FeedbackStore, create_feedback_store
from inswa.infra.foundry import create_credential
from inswa.infra.memory import MemoryStore, create_memory_store
from inswa.infra.search import SearchService, create_search_service


@dataclass
class Runtime:
    settings: Settings
    credential: Any
    registry: AgentRegistry
    factory: AgentFactory
    memory: MemoryStore
    feedback: FeedbackStore
    search: SearchService

    async def aclose(self) -> None:
        """Close every client, then the credential they share."""
        await asyncio.gather(
            self.factory.aclose(),
            self.memory.aclose(),
            self.feedback.aclose(),
            self.search.aclose(),
            return_exceptions=True,
        )
        close = getattr(self.credential, "close", None)
        if close is not None:
            await close()


async def create_runtime(
    settings: Settings, *, chat_client_factory: ChatClientFactory | None = None
) -> Runtime:
    """`chat_client_factory` is a test seam only; production always uses Foundry clients."""
    credential = create_credential(settings)
    registry = AgentRegistry.load(settings)
    return Runtime(
        settings=settings,
        credential=credential,
        registry=registry,
        factory=AgentFactory(
            settings, registry, credential=credential, chat_client_factory=chat_client_factory
        ),
        memory=create_memory_store(settings, credential=credential),
        feedback=create_feedback_store(settings, credential=credential),
        search=await create_search_service(settings, credential=credential),
    )
