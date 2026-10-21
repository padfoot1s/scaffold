from agent_framework.foundry import FoundryAgent

from inswa.agents.factory import AgentFactory
from inswa.orchestration.agent import OrchestratorAgent
from inswa.runtime import create_runtime
from tests.conftest import make_settings
from tests.fakes import FakeChatClient


async def test_follow_up_then_grounded_answer(runtime):
    agent = OrchestratorAgent(runtime)

    first = await agent.ask("What is the demand forecast for SKU ABC-123 for Contoso?", "conv-1")
    assert first.status == "follow_up"
    assert first.missing_slots == ["geography", "time_period"]
    assert "geography" in first.answer and "time period" in first.answer

    second = await agent.ask("EMEA, Q3 2026", "conv-1")
    assert second.status == "answered"
    assert second.agents_used == ["forecasting"]
    assert second.slots == {
        "geography": "EMEA",
        "time_period": "Q3 2026",
        "customer": "Contoso",
        "sku": "ABC-123",
    }
    agent_evidence = [c for c in second.citations if c.kind == "agent"]
    assert agent_evidence and "series" in agent_evidence[0].content  # real MCP tool output
    assert "[E1]" in second.answer


async def test_multiple_intents_fan_out(runtime):
    result = await OrchestratorAgent(runtime).ask(
        "Explain the drivers and variance vs actuals for SKU 9 for Fabrikam in APAC Q1 2026", "conv-2"
    )
    assert result.status == "answered"
    assert set(result.agents_used) == {"variance_analysis", "statistical_explainability"}


async def test_out_of_scope(runtime):
    result = await OrchestratorAgent(runtime).ask("What's the weather tomorrow?", "conv-3")
    assert result.status == "out_of_scope"


async def test_disabled_capability(runtime):
    result = await OrchestratorAgent(runtime).ask("Give me the root cause for SKU 1", "conv-4")
    assert result.status == "not_enabled"
    assert "Root Cause Analysis Agent" in result.answer


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
