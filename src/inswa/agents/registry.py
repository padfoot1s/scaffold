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
    # enabled_roles in dependency order; roles in one stage run concurrently.
    stages: list[list[str]]


class AgentRegistry:
    def __init__(self, settings: Settings, specs: dict[str, AgentSpec]) -> None:
        missing = {"orchestrator", *SPECIALIST_ROLES} - specs.keys()
        if missing:
            raise ValueError(f"Missing agent definitions for roles: {sorted(missing)}")
        for spec in specs.values():
            if unknown := set(spec.metadata.requires) - set(SPECIALIST_ROLES):
                raise ValueError(f"Agent '{spec.name}' requires unknown roles: {sorted(unknown)}")
        self._settings = settings
        self._specs = specs
        self._stages_for(list(SPECIALIST_ROLES))  # fail fast on dependency cycles

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
        """Roles for the intents plus the upstream roles they require, split by feature flag."""
        selected: list[str] = []
        unknown: list[str] = []

        def add(role: str) -> None:
            if role in selected:
                return
            for upstream in self._specs[role].metadata.requires:
                add(upstream)
            selected.append(role)

        for intent in intents:
            roles = [s.role for s in self.specialists(enabled_only=False) if intent in s.metadata.intents]
            if not roles:
                unknown.append(intent)
            for role in roles:
                add(role)
        enabled = [r for r in selected if self.is_enabled(r)]
        disabled = [r for r in selected if not self.is_enabled(r)]
        return Route(
            enabled_roles=enabled,
            disabled_roles=disabled,
            unknown_intents=unknown,
            stages=self._stages_for(enabled),
        )

    def _stages_for(self, roles: list[str]) -> list[list[str]]:
        """Layer `roles` so each role comes after the roles it requires.

        Requirements outside `roles` (disabled or not selected) are ignored."""
        pending = list(roles)
        done: set[str] = set()
        stages: list[list[str]] = []
        while pending:
            ready = [r for r in pending if not (set(self._specs[r].metadata.requires) & set(pending))]
            if not ready:
                raise ValueError(f"Dependency cycle between agents: {pending}")
            stages.append(ready)
            done.update(ready)
            pending = [r for r in pending if r not in done]
        return stages
