"""Which agents exist, which are enabled, and which ones handle an intent."""

from __future__ import annotations

from dataclasses import dataclass

from inswa.agents.spec import AgentSpec, load_specs
from inswa.config import SPECIALIST_ROLES, Settings


@dataclass(frozen=True)
class Route:
    enabled_roles: list[str]
    disabled_roles: list[str]
    unknown_intents: list[str]


class AgentRegistry:
    def __init__(self, settings: Settings, specs: dict[str, AgentSpec]) -> None:
        missing = {"orchestrator", *SPECIALIST_ROLES} - specs.keys()
        if missing:
            raise ValueError(f"Missing agent definitions for roles: {sorted(missing)}")
        self._settings = settings
        self._specs = specs

    @classmethod
    def load(cls, settings: Settings) -> AgentRegistry:
        return cls(settings, load_specs(settings.agents.definitions_dir))

    @property
    def orchestrator(self) -> AgentSpec:
        return self._specs["orchestrator"]

    def spec(self, role: str) -> AgentSpec:
        return self._specs[role]

    def is_enabled(self, role: str) -> bool:
        return role == "orchestrator" or self._settings.agents.toggle(role).enabled

    def specialists(self, *, enabled_only: bool = True) -> list[AgentSpec]:
        return [self._specs[r] for r in SPECIALIST_ROLES if not enabled_only or self.is_enabled(r)]

    def known_intents(self) -> list[str]:
        return [i for s in self.specialists(enabled_only=False) for i in s.metadata.intents]

    def route(self, intents: list[str]) -> Route:
        enabled: list[str] = []
        disabled: list[str] = []
        unknown: list[str] = []
        for intent in intents:
            roles = [s.role for s in self.specialists(enabled_only=False) if intent in s.metadata.intents]
            if not roles:
                unknown.append(intent)
            for role in roles:
                bucket = enabled if self.is_enabled(role) else disabled
                if role not in bucket:
                    bucket.append(role)
        return Route(enabled_roles=enabled, disabled_roles=disabled, unknown_intents=unknown)
