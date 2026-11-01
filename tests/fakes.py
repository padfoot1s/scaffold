"""Test-only fake chat client (NOT a configurable stand-in: production always uses Foundry).

It behaves just enough like a model to drive the real workflow, MCP client and tool calls.
"""

from __future__ import annotations

import json
import re

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)

CUSTOMERS = ["Contoso", "Fabrikam", "Northwind"]
INTENT_KEYWORDS = {
    "forecast": ["forecast", "demand"],
    "variance": ["variance", "actuals", "deviation"],
    "explainability": ["explain", "driver", "why"],
    "root_cause": ["root cause"],
    "recommendation": ["recommend"],
    "market_trend": ["market trend"],
}
_RUN_ID = re.compile(r"fr-\d{4}-W\d{2}-[0-9a-f]{6}")
_FIGURE = re.compile(r'"(?:forecast|variance|contribution_pct|confidence)": (-?[\d.]+)')


def _user_text(messages) -> str:
    return next((m.text for m in reversed(messages) if m.role == "user"), "")


def classify(text: str) -> dict:
    lower = text.lower()
    intents = [i for i, words in INTENT_KEYWORDS.items() if any(w in lower for w in words)]
    sku = re.search(r"\bSKU[\s-]*([A-Z0-9-]+)", text, re.IGNORECASE)
    week = re.search(r"\b\d{4}-W\d{2}\b", text)
    return {
        "intents": intents,
        "in_scope": bool(intents),
        "slots": {
            "sku": sku.group(1) if sku else None,
            "primary_customer": next((c for c in CUSTOMERS if c.lower() in lower), None),
            "week": week.group(0) if week else None,
        },
    }


def _parameters(text: str) -> dict[str, str]:
    return dict(re.findall(r"^- (sku|primary_customer|week): (.+)$", text, re.MULTILINE))


def grounded_answer(evidence_text: str) -> str:
    """Cites every evidence id and quotes one figure and the run id from the tool data."""
    ids = re.findall(r'<evidence id="([ED]\d+)"', evidence_text)
    answer = "Grounded answer " + " ".join(f"[{i}]" for i in ids)
    if figure := _FIGURE.search(evidence_text):
        answer += f" Figure: {figure.group(1)}."
    if run := _RUN_ID.search(evidence_text):
        answer += f" Forecast run {run.group(0)}."
    return answer


class FakeChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    OTEL_PROVIDER_NAME = "fake"

    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role
        self.prompts: list[str] = []

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if not stream:
            return self._respond(messages, options)

        async def _updates():
            for update in (await self._respond(messages, options)).to_updates():
                yield update

        return ResponseStream(_updates(), finalizer=ChatResponse.from_updates)

    def compose(self, evidence_text: str) -> str:
        return grounded_answer(evidence_text)

    async def _respond(self, messages, options) -> ChatResponse:
        self.prompts.append(_user_text(messages))
        if options.get("response_format") is not None:
            return ChatResponse(
                messages=[Message(role="assistant", contents=[json.dumps(classify(_user_text(messages)))])]
            )
        tools = options.get("tools") or []
        results = [c for m in messages for c in m.contents if c.type == "function_result"]
        if tools and not results:
            args = json.dumps(_parameters(_user_text(messages)))
            calls = [
                Content.from_function_call(call_id=f"call_{i}", name=t.name, arguments=args)
                for i, t in enumerate(tools)
            ]
            return ChatResponse(messages=[Message(role="assistant", contents=calls)])
        if results:
            text = f"{self.role} summary: " + " ".join(str(r.result) for r in results)
        else:
            text = self.compose(_user_text(messages))
        return ChatResponse(messages=[Message(role="assistant", contents=[text])])
