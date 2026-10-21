"""Agent definitions loaded from YAML (Agent Framework declarative `kind: Prompt` shape)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ModelSpec(BaseModel):
    # Model deployment ids are resolved from settings per role; only run options live here.
    options: dict[str, Any] = {}


class AgentMetadata(BaseModel):
    role: str
    hosted_name: str
    intents: list[str] = []
    mcp_tools: list[str] = []
    prompts: dict[str, str] = {}


class AgentSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["Prompt"] = "Prompt"
    name: str
    display_name: str = Field(alias="displayName")
    description: str
    instructions: str
    model: ModelSpec = ModelSpec()
    metadata: AgentMetadata

    @property
    def role(self) -> str:
        return self.metadata.role

    def prompt(self, key: str) -> str:
        try:
            return self.metadata.prompts[key]
        except KeyError as ex:
            raise KeyError(f"Agent '{self.name}' has no prompt '{key}' in its YAML metadata.") from ex


def load_spec(path: Path) -> AgentSpec:
    return AgentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_specs(directory: Path) -> dict[str, AgentSpec]:
    """Load every *.yaml definition in `directory`, keyed by role."""
    specs = [load_spec(p) for p in sorted(directory.glob("*.yaml"))]
    if not specs:
        raise FileNotFoundError(f"No agent definitions found in '{directory}'.")
    return {s.role: s for s in specs}
