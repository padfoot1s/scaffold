"""Command line entrypoint.

inswa ask "What is the forecast for SKU 123?" [--conversation-id ID]
inswa chat                       # multi-turn session
inswa feedback --conversation-id ID --rating 1 [--comment "..."]
inswa eval [--golden evals/golden.yaml]    # golden questions against the configured models
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from inswa.config import get_settings
from inswa.evals import load_cases, run_golden
from inswa.infra.feedback import FeedbackRecord
from inswa.infra.telemetry import setup_telemetry
from inswa.orchestration.agent import OrchestratorAgent
from inswa.orchestration.models import OrchestratorResult
from inswa.runtime import create_runtime


def _print_result(result: OrchestratorResult, conversation_id: str) -> None:
    print(f"\n{result.answer}\n")
    intents = ", ".join(result.intents) or "-"
    print(f"  status: {result.status} | intents: {intents} | conversation: {conversation_id}")
    if result.slots:
        print("  slots: " + ", ".join(f"{k}={v}" for k, v in result.slots.items()))
    if result.agents_used:
        print(f"  agents: {', '.join(result.agents_used)}")
    for c in result.citations:
        print(f"  [{c.id}] {c.kind}: {c.source}")


async def _ask(question: str, conversation_id: str) -> None:
    runtime = await create_runtime(get_settings())
    try:
        result = await OrchestratorAgent(runtime).ask(question, conversation_id)
        _print_result(result, conversation_id)
    finally:
        await runtime.aclose()


async def _chat(conversation_id: str) -> None:
    runtime = await create_runtime(get_settings())
    agent = OrchestratorAgent(runtime)
    print(f"Conversation {conversation_id}. Empty line or Ctrl-D to exit.")
    try:
        while True:
            try:
                question = input("\nyou> ").strip()
            except EOFError:
                break
            if not question:
                break
            _print_result(await agent.ask(question, conversation_id), conversation_id)
    finally:
        await runtime.aclose()


async def _feedback(conversation_id: str, rating: int, comment: str | None) -> None:
    runtime = await create_runtime(get_settings())
    try:
        record = await runtime.feedback.add(
            FeedbackRecord(conversation_id=conversation_id, rating=rating, comment=comment)
        )
        print(f"Feedback {record.id} stored.")
    finally:
        await runtime.aclose()


async def _eval(golden: Path) -> bool:
    runtime = await create_runtime(get_settings())
    try:
        results = await run_golden(OrchestratorAgent(runtime), load_cases(golden))
    finally:
        await runtime.aclose()
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.id:<28} {r.status}")
        for failure in r.failures:
            print(f"      - {failure}")
    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} golden cases passed")
    return passed == len(results)


def main() -> None:
    parser = argparse.ArgumentParser(prog="inswa")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Ask one question")
    ask.add_argument("question")
    ask.add_argument("--conversation-id", default=None)
    chat = sub.add_parser("chat", help="Interactive multi-turn session")
    chat.add_argument("--conversation-id", default=None)
    fb = sub.add_parser("feedback", help="Record feedback for a conversation")
    fb.add_argument("--conversation-id", required=True)
    fb.add_argument("--rating", type=int, choices=[-1, 0, 1], required=True)
    fb.add_argument("--comment", default=None)
    ev = sub.add_parser("eval", help="Run the golden questions and report failures")
    ev.add_argument("--golden", type=Path, default=Path("evals/golden.yaml"))
    args = parser.parse_args()

    setup_telemetry(get_settings())
    try:
        if args.command == "ask":
            asyncio.run(_ask(args.question, args.conversation_id or str(uuid.uuid4())))
        elif args.command == "chat":
            asyncio.run(_chat(args.conversation_id or str(uuid.uuid4())))
        elif args.command == "eval":
            if not asyncio.run(_eval(args.golden)):
                sys.exit(1)
        else:
            asyncio.run(_feedback(args.conversation_id, args.rating, args.comment))
    except Exception as ex:
        print(
            f"error: {ex}\nCheck FOUNDRY__PROJECT_ENDPOINT / model settings in .env, `az login`, "
            "and that the MCP server at MCP__URL is running.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
