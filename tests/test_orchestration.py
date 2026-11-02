import asyncio

import pytest
from agent_framework.foundry import FoundryAgent

from inswa.agents.factory import AgentFactory
from inswa.infra.feedback import FeedbackRecord
from inswa.orchestration.agent import OrchestratorAgent
from inswa.runtime import create_runtime
from tests.conftest import make_settings
from tests.fakes import FakeChatClient, grounded_answer


@pytest.fixture
async def recorded(settings):
    """Runtime whose fake clients are kept per model role, so tests can inspect their prompts."""
    clients: dict[str, FakeChatClient] = {}

    def make(role: str) -> FakeChatClient:
        clients[role] = FakeChatClient(role)
        return clients[role]

    rt = await create_runtime(settings, chat_client_factory=make)
    yield rt, clients
    await rt.aclose()


async def test_follow_up_then_grounded_answer(runtime):
    agent = OrchestratorAgent(runtime)

    first = await agent.ask("What is the forecast for SKU ABC-123 for Contoso?", "conv-1")
    assert first.status == "follow_up"
    assert first.missing_slots == ["week"]
    assert "week" in first.answer

    second = await agent.ask("2026-W46 please", "conv-1")
    assert second.status == "answered"
    assert second.agents_used == ["forecasting"]
    assert second.slots == {"sku": "ABC-123", "primary_customer": "Contoso", "week": "2026-W46"}
    agent_evidence = [c for c in second.citations if c.kind == "agent"]
    assert agent_evidence and '"forecast_run_id"' in agent_evidence[0].data  # real MCP tool output
    assert "[E1]" in second.answer and "Forecast run fr-" in second.answer
    assert second.unsupported_figures == []


async def test_multiple_intents_fan_out(runtime):
    result = await OrchestratorAgent(runtime).ask(
        "Explain the drivers and variance vs actuals for SKU 9 for Fabrikam in 2026-W40", "conv-2"
    )
    assert result.status == "answered"
    assert set(result.agents_used) == {"variance_analysis", "statistical_explainability"}


async def test_root_cause_runs_the_chain_with_upstream_evidence(recorded):
    runtime, clients = recorded
    result = await OrchestratorAgent(runtime).ask(
        "What is the root cause of the miss for SKU 9 for Fabrikam in 2026-W40?", "conv-rca"
    )
    assert result.status == "answered"
    assert result.agents_used == ["variance_analysis", "statistical_explainability", "rca"]
    assert [c.id for c in result.citations if c.kind == "agent"] == ["E1", "E2", "E3"]
    rca_request = clients["rca"].prompts[0]
    assert "Upstream findings" in rca_request
    assert '<evidence id="E1" kind="agent" source="Variance Analysis Agent">' in rca_request
    assert '<evidence id="E2" kind="agent" source="Statistical Explainability Agent">' in rca_request


async def test_intent_uses_router_model_and_compose_uses_reasoning_model(recorded):
    runtime, clients = recorded
    await OrchestratorAgent(runtime).ask("Forecast for SKU 1 for Contoso in 2026-W46", "conv-models")
    assert clients["router"].prompts == ["Forecast for SKU 1 for Contoso in 2026-W46"]
    assert clients["orchestrator"].prompts[0].startswith("Question:")


async def test_out_of_scope(runtime):
    result = await OrchestratorAgent(runtime).ask("What's the weather tomorrow?", "conv-3")
    assert result.status == "out_of_scope"


async def test_disabled_capability(runtime):
    result = await OrchestratorAgent(runtime).ask(
        "Show the market trend for SKU 1 at Contoso in 2026-W46", "conv-4"
    )
    assert result.status == "not_enabled"
    assert "Market Trend Agent" in result.answer


class _InventsFigures(FakeChatClient):
    """Compose drafts contain a figure no tool returned; `honest_after` drafts later it behaves."""

    honest_after = 99

    def compose(self, evidence_text: str) -> str:
        drafts = sum(p.startswith("Question:") for p in self.prompts)
        if drafts > self.honest_after:
            return grounded_answer(evidence_text)
        return "The forecast is 123456 units [E1]."


async def _ask_with(settings, client_cls, question):
    rt = await create_runtime(settings, chat_client_factory=client_cls)
    try:
        return await OrchestratorAgent(rt).ask(question, "conv-g")
    finally:
        await rt.aclose()


async def test_ungrounded_figures_fail_closed(settings):
    result = await _ask_with(settings, _InventsFigures, "Forecast for SKU 1 for Contoso in 2026-W46")
    assert result.status == "grounding_failed"
    assert result.unsupported_figures == ["123456"]
    assert "123456" not in result.answer and "couldn't verify" in result.answer


async def test_ungrounded_draft_is_retried_once(settings):
    class HonestOnRetry(_InventsFigures):
        honest_after = 1

    result = await _ask_with(settings, HonestOnRetry, "Forecast for SKU 1 for Contoso in 2026-W46")
    assert result.status == "answered"
    assert "123456" not in result.answer


async def test_slow_specialist_times_out_with_a_clear_unavailable_answer(tmp_path, mcp_url):
    class Slow(FakeChatClient):
        async def _respond(self, messages, options):
            if self.role == "forecasting":
                await asyncio.sleep(5)
            return await super()._respond(messages, options)

    settings = make_settings(tmp_path, mcp_url, orchestration={"specialist_timeout_seconds": 0.2})
    result = await _ask_with(settings, Slow, "Forecast for SKU 1 for Contoso in 2026-W46")
    assert result.status == "unavailable"
    assert "timed out" in result.citations[0].content
    assert "timed out after 0.2s" in result.answer


async def test_unreachable_tool_server_gives_actionable_answer_not_a_guess(tmp_path):
    settings = make_settings(tmp_path)  # defaults to a closed port
    result = await _ask_with(settings, FakeChatClient, "Forecast for SKU 1 for Contoso in 2026-W46")
    assert result.status == "unavailable"
    assert "could not reach the MCP tool server" in result.answer
    assert "127.0.0.1" not in result.answer  # no internal addresses in user-facing text
    assert result.citations[0].error and not result.unsupported_figures


async def test_partial_failure_still_answers_from_the_working_specialists(tmp_path, mcp_url):
    class SlowRca(FakeChatClient):
        async def _respond(self, messages, options):
            if self.role == "rca":
                await asyncio.sleep(5)
            return await super()._respond(messages, options)

    settings = make_settings(tmp_path, mcp_url, orchestration={"specialist_timeout_seconds": 1})
    result = await _ask_with(
        settings, SlowRca, "What is the root cause of the forecast miss for SKU 1 at Contoso in 2026-W40?"
    )
    assert result.status == "answered"
    failed = [c.source for c in result.citations if c.kind == "agent" and c.error]
    assert failed == ["Root Cause Analysis Agent"]
    assert any(c.kind == "agent" and not c.error for c in result.citations)


async def test_feedback_is_given_to_compose_as_data(recorded):
    runtime, clients = recorded
    await runtime.feedback.add(
        FeedbackRecord(conversation_id="conv-fb", rating=-1, comment="Use a table please")
    )
    await OrchestratorAgent(runtime).ask("Forecast for SKU 1 for Contoso in 2026-W46", "conv-fb")
    compose_prompt = clients["orchestrator"].prompts[-1]
    assert "<feedback>" in compose_prompt and "rating -1: Use a table please" in compose_prompt


async def test_hosted_transport_uses_remote_foundry_agent(tmp_path):
    settings = make_settings(
        tmp_path, agents={"forecasting": {"transport": "hosted", "hosted_name": "fc-agent"}}
    )
    rt = await create_runtime(settings, chat_client_factory=FakeChatClient)
    try:
        assert isinstance(rt.factory, AgentFactory)
        specialist = await rt.factory.build_specialist("forecasting")
        assert isinstance(specialist, FoundryAgent)
    finally:
        await rt.aclose()


async def test_agent_protocol_run_uses_session_as_conversation(runtime):
    agent = OrchestratorAgent(runtime)
    session = agent.create_session(session_id="conv-5")
    response = await agent.run("Forecast for SKU 5", session=session)
    assert response.value.status == "follow_up"
    memory = await runtime.memory.load("conv-5")
    assert memory.pending_intents == ["forecast"]
