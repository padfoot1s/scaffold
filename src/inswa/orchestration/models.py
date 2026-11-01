"""Data passed between orchestrator workflow steps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from inswa.grain import normalize_week
from inswa.infra.memory import ConversationMemory

SLOT_LABELS = {
    "sku": "SKU",
    "primary_customer": "primary customer",
    "week": "week (for example 2026-W46)",
}


class Slots(BaseModel):
    """The forecast grain the question is about: SKU x primary customer x ISO week."""

    sku: str | None = Field(default=None, description="Product SKU identifier")
    primary_customer: str | None = Field(default=None, description="Primary customer (account) name or id")
    week: str | None = Field(default=None, description="ISO week, e.g. 2026-W46")

    @field_validator("week")
    @classmethod
    def _iso_week(cls, value: str | None) -> str | None:
        # An unparseable week is treated as missing, so the follow-up step asks for it again.
        if not value or not value.strip():
            return None
        try:
            return normalize_week(value)
        except ValueError:
            return None

    def merged(self, newer: Slots) -> Slots:
        """Values stated in `newer` win; earlier values are kept otherwise."""
        return Slots(**{**self.filled(), **newer.filled()})

    def filled(self) -> dict[str, str]:
        return {k: v.strip() for k, v in self.model_dump().items() if v and v.strip()}

    def missing(self, required: list[str]) -> list[str]:
        filled = self.filled()
        return [name for name in required if name not in filled]


class ExtractedSlots(BaseModel):
    """LLM-facing slot schema: every field required (nullable) for strict structured output."""

    sku: str | None
    primary_customer: str | None
    week: str | None = Field(description="ISO week YYYY-Www, or an ISO date inside that week")


class IntentResult(BaseModel):
    """Structured output of the intent step."""

    intents: list[str] = Field(description="Allowed intents the message asks for (may be empty)")
    in_scope: bool = Field(description="Whether the message is within the assistant's domain")
    slots: ExtractedSlots

    def to_slots(self) -> Slots:
        return Slots(**self.slots.model_dump())


class OrchestratorInput(BaseModel):
    question: str
    conversation_id: str


class Evidence(BaseModel):
    id: str
    kind: Literal["agent", "document"]
    source: str
    # Specialist summary or document text.
    content: str
    # Raw tool output behind an agent's summary: the only source of figures for the answer.
    data: str | None = None


Status = Literal["answered", "follow_up", "out_of_scope", "not_enabled", "grounding_failed"]


class TurnState(BaseModel):
    request: OrchestratorInput
    memory: ConversationMemory
    effective_question: str
    intents: list[str] = []
    in_scope: bool = True
    slots: Slots = Slots()
    route: Literal["proceed", "out_of_scope", "not_enabled", "follow_up", "delegate"] = "proceed"
    # Specialists in dependency order: each inner list runs concurrently after the previous one.
    stages: list[list[str]] = []
    enabled_roles: list[str] = []
    disabled_roles: list[str] = []
    missing_slots: list[str] = []
    evidence: list[Evidence] = []


class OrchestratorResult(BaseModel):
    status: Status
    answer: str
    intents: list[str] = []
    slots: dict[str, str] = {}
    missing_slots: list[str] = []
    agents_used: list[str] = []
    citations: list[Evidence] = []
    unsupported_figures: list[str] = []
