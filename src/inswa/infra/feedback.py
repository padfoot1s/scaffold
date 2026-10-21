"""User feedback on answers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from inswa.config import Settings
from inswa.infra.documents import DocumentStore, create_document_store
from inswa.infra.secrets import SecretProvider


class FeedbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    rating: int = Field(ge=-1, le=1, description="-1 negative, 0 neutral, 1 positive")
    comment: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FeedbackStore:
    def __init__(self, documents: DocumentStore) -> None:
        self._documents = documents

    async def add(self, record: FeedbackRecord) -> FeedbackRecord:
        await self._documents.upsert(record.model_dump(mode="json"))
        return record

    async def for_conversation(self, conversation_id: str) -> list[FeedbackRecord]:
        docs = await self._documents.query("conversation_id", conversation_id)
        return [FeedbackRecord.model_validate(d) for d in docs]


async def create_feedback_store(
    settings: Settings, *, credential: Any = None, secrets: SecretProvider | None = None
) -> FeedbackStore:
    documents = await create_document_store(
        settings, settings.cosmos.feedback_container, credential=credential, secrets=secrets
    )
    return FeedbackStore(documents)
