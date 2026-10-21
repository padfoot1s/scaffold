"""Data passed between orchestrator workflow steps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from inswa.infra.memory import ConversationMemory

SLOT_LABELS = {
    "geography": "geography",
    "time_period": "time period",
    "customer": "customer",
    "sku": "SKU",
}


class Slots(BaseModel):
    geography: str | None = Field(default=None, description="Region, country or market, e.g. EMEA")
    time_period: str | None = Field(default=None, description="Period, e.g. Q3 2026 or 2026-07")
    customer: str | None = Field(default=None, description="Customer or account name")
    sku: str | None = Field(default=None, description="Product SKU identifier")

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

    geography: str | None
    time_period: str | None
    customer: str | None
    sku: str | None


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
    content: str


Status = Literal["answered", "follow_up", "out_of_scope", "not_enabled"]


class TurnState(BaseModel):
    request: OrchestratorInput
    memory: ConversationMemory
    effective_question: str
    intents: list[str] = []
    in_scope: bool = True
    slots: Slots = Slots()
    route: Literal["proceed", "out_of_scope", "not_enabled", "follow_up", "delegate"] = "proceed"
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
