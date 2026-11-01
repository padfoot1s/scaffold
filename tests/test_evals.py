from pathlib import Path

from inswa.evals import GoldenCase, check, load_cases, run_golden
from inswa.orchestration.agent import OrchestratorAgent
from inswa.orchestration.models import Evidence, OrchestratorResult

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "golden.yaml"


async def test_golden_set_passes_offline(runtime):
    """The golden set runs end to end against the mock MCP server with the fake model."""
    results = await run_golden(OrchestratorAgent(runtime), load_cases(GOLDEN))
    assert [(r.id, r.failures) for r in results if not r.passed] == []


def test_check_catches_ungrounded_and_uncited_answers():
    case = GoldenCase(id="c", turns=["q"], status="answered", agents=["forecasting"], cites_run=True)
    result = OrchestratorResult(
        status="answered",
        answer="It will be 5000 units.",
        agents_used=["forecasting"],
        citations=[
            Evidence(id="E1", kind="agent", source="F", content="", data='{"forecast_run_id": "fr-1"}')
        ],
    )
    failures = " | ".join(check(case, result))
    assert "cites no evidence" in failures
    assert "['5000']" in failures
    assert "forecast run" in failures
