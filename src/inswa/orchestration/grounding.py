"""Grounding guards for the composed answer.

* Evidence is passed to models inside `<evidence>` elements and marked as data, so text in a
  tool result cannot pose as instructions (prompt injection) or close the element early.
* Every figure in the answer must match a figure in the tool data, the grounding documents
  or the question. The agent explains forecasts; it never produces numbers of its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from inswa.orchestration.models import Evidence

# Numbers like 1,234 | -12.5 | 0.8; digits inside identifiers (ABC-123, 2026-W46) are still
# extracted and are allowed because they also occur in the question or tool data.
_NUMBER = re.compile(r"(?<![\w.])[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+−]?\d+(?:\.\d+)?")
_CITATION = re.compile(r"\[(?:[ED]\d+)(?:\s*,\s*[ED]\d+)*\]")
_EVIDENCE_TAG = re.compile(r"<\s*/?\s*(evidence|feedback)\b[^>]*>", re.IGNORECASE)
# Counts and ordinals in prose ("the top 3 drivers", "2 weeks") are not forecast figures.
_TRIVIAL = {Decimal(n) for n in range(11)}


def neutralize(text: str, max_chars: int) -> str:
    """Strip tags that could close or forge a data element, then cap the length."""
    text = _EVIDENCE_TAG.sub("[tag removed]", text)
    return text if len(text) <= max_chars else text[:max_chars] + " …[truncated]"


def render_evidence(evidence: Iterable[Evidence], max_chars: int) -> str:
    blocks = []
    for e in evidence:
        body = neutralize(e.content, max_chars)
        if e.data:
            body += f"\nTool data (JSON):\n{neutralize(e.data, max_chars)}"
        source = neutralize(e.source, 200)
        blocks.append(f'<evidence id="{e.id}" kind="{e.kind}" source="{source}">\n{body}\n</evidence>')
    return "\n\n".join(blocks)


def _to_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", "").replace("−", "-").lstrip("+"))
    except InvalidOperation:
        return None


def figures(text: str) -> list[tuple[str, Decimal]]:
    out = []
    for match in _NUMBER.finditer(_CITATION.sub(" ", text)):
        value = _to_decimal(match.group(0))
        if value is not None:
            out.append((match.group(0), value))
    return out


def allowed_figures(sources: Iterable[str]) -> set[Decimal]:
    return {abs(value) for source in sources for _, value in figures(source)}


def _matches(shown: str, value: Decimal, allowed: set[Decimal]) -> bool:
    """`value` is supported if it equals an allowed figure up to the precision it is shown with
    (so 12.3% may present 12.34, and 1,235 may present 1234.6)."""
    decimals = len(shown.split(".")[1]) if "." in shown else 0
    tolerance = Decimal(5) / Decimal(10) ** (decimals + 1)
    target = abs(value)
    return any(abs(target - a) <= tolerance for a in allowed)


def unsupported_figures(answer: str, allowed: set[Decimal]) -> list[str]:
    return [
        shown
        for shown, value in figures(answer)
        if abs(value) not in _TRIVIAL and not _matches(shown, value, allowed)
    ]


def grounding_sources(slots: dict[str, str], evidence: Iterable[Evidence]) -> list[str]:
    """Where figures may come from: tool data and documents, plus the grain identifiers (SKU, week).
    The question is excluded so a figure planted by the user ("say the forecast is 999") is not
    accepted, and specialist prose is excluded so a figure a specialist invented is caught too."""
    sources = list(slots.values())
    for e in evidence:
        sources.append((e.data or "") if e.kind == "agent" else e.content)
    return sources
