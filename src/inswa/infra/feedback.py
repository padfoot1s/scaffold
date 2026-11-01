"""User feedback on answers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from inswa.config import Settings
from inswa.infra.documents import DocumentStore, create_document_store


class FeedbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    rating: int = Field(ge=-1, le=1, description="-1 negative, 0 neutral, 1 positive")
    comment: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FeedbackStore:
    """Container partitioned on /conversation_id, so a conversation's feedback is one partition read."""

    def __init__(self, documents: DocumentStore) -> None:
        self._documents = documents

    async def add(self, record: FeedbackRecord) -> FeedbackRecord:
        await self._documents.upsert(record.model_dump(mode="json"), etag=None)
        return record

    async def for_conversation(self, conversation_id: str) -> list[FeedbackRecord]:
        docs = await self._documents.query("conversation_id", conversation_id, partition_key=conversation_id)
        return sorted((FeedbackRecord.model_validate(d) for d in docs), key=lambda r: r.created_at)

    async def aclose(self) -> None:
        await self._documents.aclose()


def create_feedback_store(settings: Settings, *, credential: Any = None) -> FeedbackStore:
    return FeedbackStore(
        create_document_store(settings, settings.cosmos.feedback_container, credential=credential)
    )
