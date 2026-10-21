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

GEOGRAPHIES = ["EMEA", "APAC", "LATAM", "North America"]
CUSTOMERS = ["Contoso", "Fabrikam", "Northwind"]
INTENT_KEYWORDS = {
    "forecast": ["forecast", "demand"],
    "variance": ["variance", "actuals", "deviation"],
    "explainability": ["explain", "driver", "why"],
    "root_cause": ["root cause"],
    "market_trend": ["market trend"],
}


def _user_text(messages) -> str:
    return next((m.text for m in reversed(messages) if m.role == "user"), "")


def classify(text: str) -> dict:
    lower = text.lower()
    intents = [i for i, words in INTENT_KEYWORDS.items() if any(w in lower for w in words)]
    sku = re.search(r"\bSKU[\s-]*([A-Z0-9-]+)", text, re.IGNORECASE)
    period = re.search(r"\bQ[1-4]\s+\d{4}\b", text)
    return {
        "intents": intents,
        "in_scope": bool(intents),
        "slots": {
            "geography": next((g for g in GEOGRAPHIES if g.lower() in lower), None),
            "time_period": period.group(0) if period else None,
            "customer": next((c for c in CUSTOMERS if c.lower() in lower), None),
            "sku": sku.group(1) if sku else None,
        },
    }


def _parameters(text: str) -> dict[str, str]:
    return dict(re.findall(r"^- (\w+): (.+)$", text, re.MULTILINE))


class FakeChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    OTEL_PROVIDER_NAME = "fake"

    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if not stream:
            return self._respond(messages, options)

        async def _updates():
            for update in (await self._respond(messages, options)).to_updates():
                yield update

        return ResponseStream(_updates(), finalizer=ChatResponse.from_updates)

    async def _respond(self, messages, options) -> ChatResponse:
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
            ids = re.findall(r"^\[([ED]\d+)\]", _user_text(messages), re.MULTILINE)
            text = "Grounded answer " + " ".join(f"[{i}]" for i in ids)
        return ChatResponse(messages=[Message(role="assistant", contents=[text])])
