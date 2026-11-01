"""Golden-question evaluation of the orchestrator (see evals/golden.yaml).

Deterministic checks on the structured `OrchestratorResult`: status, specialists used,
citations, forecast-run citation, forbidden strings and, independently of the in-workflow
guard, that every figure in the answer appears in the tool data or documents.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from inswa.orchestration.agent import OrchestratorAgent
from inswa.orchestration.grounding import allowed_figures, grounding_sources, unsupported_figures
from inswa.orchestration.models import OrchestratorResult

_RUN_ID = re.compile(r'"forecast_run_id"\s*:\s*"([^"]+)"')
_CITE = re.compile(r"\[[ED]\d+")


class GoldenCase(BaseModel):
    id: str
    turns: list[str]
    status: str | list[str]
    agents: list[str] = []
    cites_run: bool = False
    forbid: list[str] = []


class CaseResult(BaseModel):
    id: str
    passed: bool
    status: str
    failures: list[str] = Field(default_factory=list)
    answer: str = ""


def load_cases(path: Path) -> list[GoldenCase]:
    return [GoldenCase.model_validate(c) for c in yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]]


def check(case: GoldenCase, result: OrchestratorResult) -> list[str]:
    failures = []
    expected = [case.status] if isinstance(case.status, str) else case.status
    if result.status not in expected:
        failures.append(f"status {result.status!r}, expected {' or '.join(expected)}")
    if missing := [a for a in case.agents if a not in result.agents_used]:
        failures.append(f"specialists not used: {missing}")
    for text in case.forbid:
        if text in result.answer:
            failures.append(f"answer contains forbidden {text!r}")
    if result.status == "answered":
        if not _CITE.search(result.answer):
            failures.append("answer cites no evidence")
        allowed = allowed_figures(grounding_sources(result.slots, result.citations))
        if unsupported := unsupported_figures(result.answer, allowed):
            failures.append(f"figures not in tool data: {unsupported}")
        if case.cites_run:
            run_ids = {m for c in result.citations for m in _RUN_ID.findall(c.data or "")}
            if not any(r in result.answer for r in run_ids):
                failures.append(
                    f"answer does not name the forecast run ({sorted(run_ids) or 'none returned'})"
                )
    return failures


async def run_case(agent: OrchestratorAgent, case: GoldenCase) -> CaseResult:
    conversation_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
    result = None
    for turn in case.turns:
        result = await agent.ask(turn, conversation_id)
    assert result is not None, f"case {case.id} has no turns"
    failures = check(case, result)
    return CaseResult(
        id=case.id, passed=not failures, status=result.status, failures=failures, answer=result.answer
    )


async def run_golden(agent: OrchestratorAgent, cases: list[GoldenCase]) -> list[CaseResult]:
    # Sequential on purpose: keeps model load low and the report in file order.
    return [await run_case(agent, case) for case in cases]
