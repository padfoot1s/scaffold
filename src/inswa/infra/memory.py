"""Conversation memory (slots carried across turns, pending intents, turn history)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from inswa.config import Settings
from inswa.infra.documents import DocumentStore, create_document_store
from inswa.infra.secrets import SecretProvider


class TurnRecord(BaseModel):
    question: str
    answer: str
    status: str
    intents: list[str] = []
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationMemory(BaseModel):
    id: str
    slots: dict[str, str] = {}
    pending_intents: list[str] = []
    pending_question: str | None = None
    turns: list[TurnRecord] = []


class MemoryStore:
    def __init__(self, documents: DocumentStore, max_turns: int = 20) -> None:
        self._documents = documents
        self._max_turns = max_turns

    async def load(self, conversation_id: str) -> ConversationMemory:
        doc = await self._documents.get(conversation_id)
        return ConversationMemory.model_validate(doc) if doc else ConversationMemory(id=conversation_id)

    async def save(self, memory: ConversationMemory) -> None:
        memory.turns = memory.turns[-self._max_turns :]
        await self._documents.upsert(memory.model_dump(mode="json"))


async def create_memory_store(
    settings: Settings, *, credential: Any = None, secrets: SecretProvider | None = None
) -> MemoryStore:
    documents = await create_document_store(
        settings, settings.cosmos.memory_container, credential=credential, secrets=secrets
    )
    return MemoryStore(documents)
