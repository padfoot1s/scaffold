"""The orchestrator exposed as an Agent Framework agent so it can be a Foundry hosted agent.

Each run executes a freshly built workflow. The agent session id is the conversation id used
for memory, so follow-up answers resume the pending request.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    AgentSession,
    BaseAgent,
    Content,
    Message,
    ResponseStream,
)

from inswa.orchestration.models import OrchestratorInput, OrchestratorResult
from inswa.orchestration.workflow import build_workflow
from inswa.runtime import Runtime


def _last_user_text(messages: Any) -> str:
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, Message):
        messages = [messages]
    if isinstance(messages, Sequence):
        for message in reversed(list(messages)):
            if isinstance(message, str):
                return message
            if isinstance(message, Message) and message.role == "user":
                return message.text
    return str(messages)


class OrchestratorAgent(BaseAgent):
    def __init__(self, runtime: Runtime) -> None:
        spec = runtime.registry.orchestrator
        super().__init__(id=spec.name, name=spec.name, description=spec.description)
        self._runtime = runtime

    async def ask(self, question: str, conversation_id: str) -> OrchestratorResult:
        workflow = build_workflow(self._runtime)
        run = await workflow.run(OrchestratorInput(question=question, conversation_id=conversation_id))
        outputs = [o for o in run.get_outputs() if isinstance(o, OrchestratorResult)]
        if not outputs:
            raise RuntimeError("The orchestrator workflow finished without a result.")
        return outputs[-1]

    def _to_response(self, result: OrchestratorResult) -> AgentResponse:
        return AgentResponse(
            messages=[Message(role="assistant", contents=[result.answer], author_name=self.name)],
            response_id=f"resp_{uuid.uuid4().hex}",
            agent_id=self.id,
            value=result,
            additional_properties={"orchestrator": result.model_dump(mode="json")},
        )

    async def _run(self, messages: Any, session: AgentSession | None) -> AgentResponse:
        conversation_id = session.session_id if session else str(uuid.uuid4())
        return self._to_response(await self.ask(_last_user_text(messages), conversation_id))

    async def _stream(
        self, messages: Any, session: AgentSession | None
    ) -> AsyncIterator[AgentResponseUpdate]:
        response = await self._run(messages, session)
        yield AgentResponseUpdate(
            contents=[Content.from_text(response.text)],
            role="assistant",
            author_name=self.name,
            agent_id=self.id,
            response_id=response.response_id,
            additional_properties=response.additional_properties,
        )

    def run(  # type: ignore[override]
        self,
        messages: Any = None,
        *,
        stream: bool = False,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> Any:
        if stream:
            return ResponseStream(self._stream(messages, session), finalizer=AgentResponse.from_updates)
        return self._run(messages, session)
