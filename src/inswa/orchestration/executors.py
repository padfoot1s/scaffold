"""Orchestrator workflow steps: intent -> scope -> slots -> (follow-up | delegate -> compose).

Note: no `from __future__ import annotations` here; the workflow engine inspects handler
type hints at runtime to validate edges.
"""

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Never

from agent_framework import Content, Executor, WorkflowContext, handler
from agent_framework.observability import get_tracer

from inswa.infra.memory import TurnRecord
from inswa.orchestration.models import (
    SLOT_LABELS,
    Evidence,
    IntentResult,
    OrchestratorInput,
    OrchestratorResult,
    Slots,
    TurnState,
)
from inswa.runtime import Runtime

logger = logging.getLogger(__name__)
_tracer = get_tracer("inswa.orchestrator")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}"


async def _finish(
    runtime: Runtime, state: TurnState, result: OrchestratorResult, *, keep_pending: bool
) -> None:
    memory = state.memory
    memory.slots = state.slots.filled()
    if keep_pending:
        memory.pending_intents = state.intents
        memory.pending_question = state.effective_question
    else:
        memory.pending_intents = []
        memory.pending_question = None
    memory.turns.append(
        TurnRecord(
            question=state.request.question, answer=result.answer, status=result.status, intents=state.intents
        )
    )
    await runtime.memory.save(memory)


class IntentExecutor(Executor):
    """Step 1 - find the intent and extract slots, merged with what the conversation already knows."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="intent")
        self._runtime = runtime

    @handler
    async def handle(self, request: OrchestratorInput, ctx: WorkflowContext[TurnState]) -> None:
        with _tracer.start_as_current_span("orchestrator.intent") as span:
            memory = await self._runtime.memory.load(request.conversation_id)
            registry = self._runtime.registry
            known_context = json.dumps(
                {
                    "slots": memory.slots,
                    "pending_intents": memory.pending_intents,
                    "pending_question": memory.pending_question,
                }
            )
            prompt = registry.orchestrator.prompt("intent").format(
                allowed_intents=", ".join(registry.known_intents()), known_context=known_context
            )
            agent = self._runtime.factory.build_orchestrator_step_agent("intent", prompt)
            response = await agent.run(request.question, options={"response_format": IntentResult})
            result = (
                response.value
                if isinstance(response.value, IntentResult)
                else (IntentResult.model_validate_json(response.text))
            )

            intents = [i for i in result.intents if i in registry.known_intents()]
            in_scope = result.in_scope
            effective_question = request.question
            if not intents and memory.pending_intents:
                # The user is answering our follow-up question: resume the pending request.
                intents, in_scope = list(memory.pending_intents), True
            if memory.pending_question and intents == memory.pending_intents:
                effective_question = f"{memory.pending_question}\n(Additional details: {request.question})"

            slots = Slots(**memory.slots).merged(result.to_slots())
            span.set_attribute("inswa.intents", intents)
            span.set_attribute("inswa.in_scope", in_scope)
            await ctx.send_message(
                TurnState(
                    request=request,
                    memory=memory,
                    effective_question=effective_question,
                    intents=intents,
                    in_scope=in_scope,
                    slots=slots,
                )
            )


class ScopeExecutor(Executor):
    """Step 2 - check scope and that the agents needed are enabled."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="scope")
        self._runtime = runtime

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[TurnState]) -> None:
        with _tracer.start_as_current_span("orchestrator.scope") as span:
            route = self._runtime.registry.route(state.intents)
            state.enabled_roles = route.enabled_roles
            state.disabled_roles = route.disabled_roles
            if not state.in_scope or not state.intents:
                state.route = "out_of_scope"
            elif not route.enabled_roles:
                state.route = "not_enabled" if route.disabled_roles else "out_of_scope"
            else:
                state.route = "proceed"
            span.set_attribute("inswa.route", state.route)
            await ctx.send_message(state)


class SlotExecutor(Executor):
    """Step 3 - make sure geography, time period, customer and SKU are known."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="slots")
        self._runtime = runtime

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[TurnState]) -> None:
        with _tracer.start_as_current_span("orchestrator.slots") as span:
            state.missing_slots = state.slots.missing(self._runtime.settings.orchestration.required_slots)
            state.route = "follow_up" if state.missing_slots else "delegate"
            span.set_attribute("inswa.missing_slots", state.missing_slots)
            await ctx.send_message(state)


class FollowUpExecutor(Executor):
    """Ask for the missing slots; the next turn resumes from conversation memory."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="follow_up")
        self._runtime = runtime

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[Never, OrchestratorResult]) -> None:
        missing = [SLOT_LABELS.get(s, s) for s in state.missing_slots]
        answer = self._runtime.registry.orchestrator.prompt("follow_up").format(missing=_join(missing))
        result = OrchestratorResult(
            status="follow_up",
            answer=answer,
            intents=state.intents,
            slots=state.slots.filled(),
            missing_slots=state.missing_slots,
        )
        await _finish(self._runtime, state, result, keep_pending=True)
        await ctx.yield_output(result)


class RejectExecutor(Executor):
    """Out-of-scope questions and capabilities that are switched off."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="reject")
        self._runtime = runtime

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[Never, OrchestratorResult]) -> None:
        spec = self._runtime.registry.orchestrator
        if state.route == "not_enabled":
            names = [self._runtime.registry.spec(r).display_name for r in state.disabled_roles]
            answer = spec.prompt("not_enabled").format(capabilities=_join(names))
        else:
            answer = spec.prompt("out_of_scope")
        result = OrchestratorResult(
            status="not_enabled" if state.route == "not_enabled" else "out_of_scope",
            answer=answer,
            intents=state.intents,
            slots=state.slots.filled(),
        )
        await _finish(self._runtime, state, result, keep_pending=False)
        await ctx.yield_output(result)


def _tool_results(response) -> list[str]:
    results = []
    for message in response.messages:
        for content in message.contents:
            if isinstance(content, Content) and content.type == "function_result":
                results.append(str(content.result))
    return results


class DelegateExecutor(Executor):
    """Step 4 - run the specialists for the intent (concurrently); collect their output as evidence."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="delegate")
        self._runtime = runtime

    async def _call(self, role: str, request: str) -> tuple[str, str]:
        spec = self._runtime.registry.spec(role)
        with _tracer.start_as_current_span(f"orchestrator.delegate.{role}"):
            try:
                agent = await self._runtime.factory.build_specialist(role)
                async with AsyncExitStack() as stack:
                    if hasattr(agent, "__aenter__"):
                        await stack.enter_async_context(agent)
                    response = await agent.run(request)
                tool_data = _tool_results(response)
                content = response.text
                if tool_data:
                    content += "\nTool data: " + " | ".join(tool_data)
                return spec.display_name, content
            except Exception as ex:  # a failing specialist must not sink the whole answer
                logger.exception("Specialist '%s' failed", role)
                return (
                    spec.display_name,
                    f"UNAVAILABLE: the {spec.display_name} failed ({type(ex).__name__}).",
                )

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[TurnState]) -> None:
        with _tracer.start_as_current_span("orchestrator.delegate") as span:
            span.set_attribute("inswa.agents", state.enabled_roles)
            params = "\n".join(f"- {k}: {v}" for k, v in state.slots.filled().items())
            request = f"{state.effective_question}\n\nParameters:\n{params}"
            outputs = await asyncio.gather(*(self._call(role, request) for role in state.enabled_roles))
            state.evidence = [
                Evidence(id=f"E{i}", kind="agent", source=source, content=content)
                for i, (source, content) in enumerate(outputs, start=1)
            ]
            await ctx.send_message(state)


class ComposeExecutor(Executor):
    """Step 5 - compose an answer grounded only in specialist evidence and search documents."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(id="compose")
        self._runtime = runtime

    @handler
    async def handle(self, state: TurnState, ctx: WorkflowContext[Never, OrchestratorResult]) -> None:
        with _tracer.start_as_current_span("orchestrator.compose"):
            settings = self._runtime.settings
            query = " ".join([state.effective_question, *state.intents])
            hits = await self._runtime.search.search(query, settings.search.top_k)
            evidence = state.evidence + [
                Evidence(id=f"D{i}", kind="document", source=h.id, content=f"{h.title}: {h.content}")
                for i, h in enumerate(hits, start=1)
            ]
            evidence_block = "\n\n".join(f"[{e.id}] ({e.source})\n{e.content}" for e in evidence)
            agent = self._runtime.factory.build_orchestrator_step_agent(
                "compose", self._runtime.registry.orchestrator.prompt("compose")
            )
            response = await agent.run(f"Question: {state.effective_question}\n\nEvidence:\n{evidence_block}")
            answer = response.text
            if state.disabled_roles:
                names = [self._runtime.registry.spec(r).display_name for r in state.disabled_roles]
                answer += "\n\n" + self._runtime.registry.orchestrator.prompt("not_enabled").format(
                    capabilities=_join(names)
                )
            result = OrchestratorResult(
                status="answered",
                answer=answer,
                intents=state.intents,
                slots=state.slots.filled(),
                agents_used=state.enabled_roles,
                citations=evidence,
            )
            await _finish(self._runtime, state, result, keep_pending=False)
            await ctx.yield_output(result)
