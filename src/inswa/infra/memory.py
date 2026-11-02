"""Conversation memory (slots carried across turns, pending intents, turn history)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field, PrivateAttr

from inswa.config import Settings
from inswa.infra.documents import ETAG, ConcurrentUpdateError, DocumentStore, create_document_store


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
    _etag: str | None = PrivateAttr(default=None)


def document_key(conversation_id: str) -> str:
    """Document id (= partition key) for a conversation.

    Cosmos rejects ids containing / \\ ? #, and conversation ids can come from callers. Percent-encoding
    is injective and leaves ordinary ids (letters, digits, `-_.~`) unchanged.
    """
    return quote(conversation_id, safe="")


class MemoryStore:
    """Container partitioned on /id (the encoded conversation id, see `document_key`)."""

    def __init__(self, documents: DocumentStore, max_turns: int = 20, max_attempts: int = 3) -> None:
        self._documents = documents
        self._max_turns = max_turns
        self._max_attempts = max_attempts

    async def load(self, conversation_id: str) -> ConversationMemory:
        key = document_key(conversation_id)
        doc = await self._documents.get(key, partition_key=key)
        if not doc:
            return ConversationMemory(id=conversation_id)
        memory = ConversationMemory.model_validate({**doc, "id": conversation_id})
        memory._etag = doc.get(ETAG)
        return memory

    async def save(self, memory: ConversationMemory) -> None:
        memory.turns = memory.turns[-self._max_turns :]
        doc = {**memory.model_dump(mode="json"), "id": document_key(memory.id), "conversation_id": memory.id}
        memory._etag = await self._documents.upsert(doc, etag=memory._etag)

    async def update(self, memory: ConversationMemory, change: Callable[[ConversationMemory], None]) -> None:
        """Apply `change` and save; on a concurrent write, reload and re-apply it to the latest version."""
        for attempt in range(self._max_attempts):
            change(memory)
            try:
                await self.save(memory)
                return
            except ConcurrentUpdateError:
                if attempt == self._max_attempts - 1:
                    raise
                memory = await self.load(memory.id)

    async def aclose(self) -> None:
        await self._documents.aclose()


def create_memory_store(settings: Settings, *, credential: Any = None) -> MemoryStore:
    return MemoryStore(
        create_document_store(settings, settings.cosmos.memory_container, credential=credential)
    )
