"""Deterministic synthetic tool responses. Replace with the real MCP server by changing MCP__URL.

Tool contract `stub-0.1` (inferred; to be agreed with the MCP server team):

* Inputs: the forecast grain `sku`, `primary_customer`, `week` (ISO week `YYYY-Www` or a date
  in that week) plus an optional `forecast_run_id` (default: latest run).
* Outputs: the grain echoed back, `forecast_run_id`, `model_version`, `as_of` and `unit`, so
  the agent can cite exactly which forecast run a figure came from.
* All arithmetic (variance, totals, percentages) happens here, never in the agent.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from inswa.grain import parse_week, week_label

CONTRACT_VERSION = "stub-0.1"
MODEL_VERSION = "weekly-ensemble-2026.10"
VARIANCE_THRESHOLD_PCT = 10.0

Sku = Annotated[str, Field(description="Product SKU identifier")]
PrimaryCustomer = Annotated[str, Field(description="Primary customer (account) name or id")]
Week = Annotated[str, Field(description="ISO week YYYY-Www (e.g. 2026-W46) or an ISO date in that week")]
RunId = Annotated[str | None, Field(description="Forecast run id; omit for the latest run")]


def _rng(*parts: str) -> random.Random:
    seed = hashlib.sha256("|".join(p.lower().strip() for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _run(sku: str, customer: str, week_start: date, forecast_run_id: str | None) -> dict[str, Any]:
    """The forecast run the answer is based on: produced the Monday before the first forecast week."""
    as_of = week_start - timedelta(days=7)
    digest = hashlib.sha256(f"{sku}|{customer}|{as_of}".lower().encode()).hexdigest()[:6]
    return {
        "forecast_run_id": forecast_run_id or f"fr-{week_label(as_of)}-{digest}",
        "model_version": MODEL_VERSION,
        "as_of": as_of.isoformat(),
    }


def _header(sku: str, customer: str, week_start: date, forecast_run_id: str | None) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "stub": True,
        "sku": sku,
        "primary_customer": customer,
        "week": week_label(week_start),
        "unit": "units",
        **_run(sku, customer, week_start, forecast_run_id),
    }


def _weekly_base(sku: str, customer: str) -> int:
    return _rng("base", sku, customer).randint(200, 1500)


def build_server() -> MCPServer:
    server = MCPServer("inswa-mock-tools", version=CONTRACT_VERSION)

    @server.tool()
    def get_forecast(
        sku: Sku,
        primary_customer: PrimaryCustomer,
        week: Week,
        horizon_weeks: Annotated[int, Field(ge=1, le=26, description="Weeks to return from `week`")] = 4,
        forecast_run_id: RunId = None,
    ) -> dict[str, Any]:
        """Weekly volume forecast with a P10-P90 interval for `horizon_weeks` weeks starting at `week`."""
        start = parse_week(week)
        base = _weekly_base(sku, primary_customer)
        series = []
        for h in range(horizon_weeks):
            week_start = start + timedelta(weeks=h)
            point = round(base * _rng("forecast", sku, primary_customer, str(week_start)).uniform(0.85, 1.2))
            series.append(
                {
                    "week": week_label(week_start),
                    "week_start": week_start.isoformat(),
                    "horizon_weeks": h + 1,
                    "forecast": point,
                    "p10": round(point * 0.85),
                    "p90": round(point * 1.15),
                }
            )
        return {
            **_header(sku, primary_customer, start, forecast_run_id),
            "series": series,
            "accuracy": {
                "metric": "wMAPE",
                "value_pct": round(_rng("acc", sku, primary_customer).uniform(8, 22), 1),
                "window_weeks": 13,
            },
        }

    @server.tool()
    def analyze_variance(
        sku: Sku,
        primary_customer: PrimaryCustomer,
        week: Week,
        lookback_weeks: Annotated[
            int, Field(ge=1, le=26, description="Weeks up to and including `week`")
        ] = 4,
        forecast_run_id: RunId = None,
    ) -> dict[str, Any]:
        """Forecast vs actuals per week (variance = actual - forecast), computed server-side."""
        end = parse_week(week)
        base = _weekly_base(sku, primary_customer)
        rows = []
        for back in reversed(range(lookback_weeks)):
            week_start = end - timedelta(weeks=back)
            rng = _rng("variance", sku, primary_customer, str(week_start))
            forecast = round(base * rng.uniform(0.85, 1.2))
            actual = round(forecast * rng.uniform(0.75, 1.25))
            variance_pct = round((actual - forecast) / forecast * 100, 1)
            rows.append(
                {
                    "week": week_label(week_start),
                    "forecast": forecast,
                    "actual": actual,
                    "variance": actual - forecast,
                    "variance_pct": variance_pct,
                    "flagged": abs(variance_pct) >= VARIANCE_THRESHOLD_PCT,
                }
            )
        total_forecast = sum(r["forecast"] for r in rows)
        total_actual = sum(r["actual"] for r in rows)
        largest = max(rows, key=lambda r: abs(r["variance_pct"]))
        return {
            **_header(sku, primary_customer, end - timedelta(weeks=lookback_weeks - 1), forecast_run_id),
            "week": week_label(end),
            "threshold_pct": VARIANCE_THRESHOLD_PCT,
            "weeks": rows,
            "summary": {
                "total_forecast": total_forecast,
                "total_actual": total_actual,
                "total_variance": total_actual - total_forecast,
                "total_variance_pct": round((total_actual - total_forecast) / total_forecast * 100, 1),
                "largest_deviation_week": largest["week"],
                "flagged_weeks": [r["week"] for r in rows if r["flagged"]],
            },
        }

    @server.tool()
    def explain_forecast(
        sku: Sku, primary_customer: PrimaryCustomer, week: Week, forecast_run_id: RunId = None
    ) -> dict[str, Any]:
        """Driver contributions (share of forecast movement vs baseline) behind the forecast for `week`."""
        start = parse_week(week)
        rng = _rng("explain", sku, primary_customer, str(start))
        drivers = ["price", "promotions", "seasonality", "distribution", "macro_index"]
        weights = [rng.random() for _ in drivers]
        total = sum(weights)
        contributions = sorted(
            (
                {
                    "driver": d,
                    "contribution_pct": round(w / total * 100, 1),
                    "direction": rng.choice(["up", "down"]),
                }
                for d, w in zip(drivers, weights, strict=True)
            ),
            key=lambda c: c["contribution_pct"],
            reverse=True,
        )
        return {
            **_header(sku, primary_customer, start, forecast_run_id),
            "method": "shap",
            "drivers": contributions,
        }

    @server.tool()
    def get_root_causes(
        sku: Sku, primary_customer: PrimaryCustomer, week: Week, forecast_run_id: RunId = None
    ) -> dict[str, Any]:
        """Candidate root causes for forecast misses around `week`, each with the signal supporting it."""
        start = parse_week(week)
        rng = _rng("rca", sku, primary_customer, str(start))
        candidates = [
            ("promotion_timing", "Promotion calendar for this customer moved after the forecast run."),
            ("price_change", "Shelf price changed during the lookback window."),
            ("out_of_stock", "Shipments were constrained by supply in at least one flagged week."),
            ("distribution_change", "Store count carrying the SKU changed for this customer."),
        ]
        scored = sorted(
            ({"cause": c, "signal": s, "confidence": round(rng.uniform(0.2, 0.9), 2)} for c, s in candidates),
            key=lambda c: c["confidence"],
            reverse=True,
        )
        return {**_header(sku, primary_customer, start, forecast_run_id), "candidates": scored[:3]}

    @server.tool()
    def get_market_trends(
        sku: Sku, primary_customer: PrimaryCustomer, week: Week, forecast_run_id: RunId = None
    ) -> dict[str, Any]:
        """Market trends relevant to the SKU and customer (placeholder)."""
        start = parse_week(week)
        return {**_header(sku, primary_customer, start, forecast_run_id), "trends": ["placeholder"]}

    @server.tool()
    def get_market_recommendations(
        sku: Sku, primary_customer: PrimaryCustomer, week: Week, forecast_run_id: RunId = None
    ) -> dict[str, Any]:
        """Planner actions for the SKU and customer, for review by the demand planning team."""
        start = parse_week(week)
        return {
            **_header(sku, primary_customer, start, forecast_run_id),
            "recommendations": [
                {
                    "action": "review_promotion_inputs",
                    "rationale": "Confirm the forecast run used the customer's current promotion calendar.",
                    "priority": "high",
                },
                {
                    "action": "review_safety_stock",
                    "rationale": "Check safety stock for the flagged weeks against the forecast interval.",
                    "priority": "medium",
                },
            ],
        }

    return server
