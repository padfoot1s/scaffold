"""Deterministic synthetic tool responses. Replace with the real MCP server by changing MCP__URL."""

from __future__ import annotations

import hashlib
import random
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

Geography = Annotated[str, Field(description="Region, country or market, e.g. EMEA")]
TimePeriod = Annotated[str, Field(description="Period, e.g. Q3 2026")]
Customer = Annotated[str, Field(description="Customer or account name")]
Sku = Annotated[str, Field(description="Product SKU identifier")]


def _rng(*parts: str) -> random.Random:
    seed = hashlib.sha256("|".join(p.lower().strip() for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _periods(time_period: str) -> list[str]:
    return [f"{time_period} M{i}" for i in range(1, 4)]


def _key(geography: str, time_period: str, customer: str, sku: str) -> dict[str, str]:
    return {"geography": geography, "time_period": time_period, "customer": customer, "sku": sku}


def build_server(host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    server = FastMCP("inswa-mock-tools", host=host, port=port, stateless_http=True)

    @server.tool()
    def get_forecast(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Demand forecast (units) with a P10-P90 interval per period."""
        rng = _rng("forecast", geography, time_period, customer, sku)
        base = rng.randint(800, 5000)
        series = []
        for period in _periods(time_period):
            point = round(base * rng.uniform(0.9, 1.15))
            series.append(
                {"period": period, "forecast": point, "p10": round(point * 0.88), "p90": round(point * 1.12)}
            )
        return {
            **_key(geography, time_period, customer, sku),
            "unit": "units",
            "model": "mock-ensemble-v1",
            "mape_pct": round(rng.uniform(6, 18), 1),
            "series": series,
        }

    @server.tool()
    def analyze_variance(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Forecast vs actuals variance per period."""
        rng = _rng("variance", geography, time_period, customer, sku)
        rows = []
        for period in _periods(time_period):
            forecast = rng.randint(800, 5000)
            actual = round(forecast * rng.uniform(0.8, 1.2))
            rows.append(
                {
                    "period": period,
                    "forecast": forecast,
                    "actual": actual,
                    "variance": actual - forecast,
                    "variance_pct": round((actual - forecast) / forecast * 100, 1),
                }
            )
        largest = max(rows, key=lambda r: abs(r["variance_pct"]))
        return {
            **_key(geography, time_period, customer, sku),
            "unit": "units",
            "periods": rows,
            "largest_deviation_period": largest["period"],
        }

    @server.tool()
    def explain_forecast(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Driver contributions (share of forecast movement) behind the forecast."""
        rng = _rng("explain", geography, time_period, customer, sku)
        drivers = ["price", "promotions", "seasonality", "distribution", "macro_index"]
        weights = [rng.random() for _ in drivers]
        total = sum(weights)
        contributions = sorted(
            (
                {
                    "driver": d,
                    "contribution_pct": round(w / total * 100, 1),
                    "direction": rng.choice(["+", "-"]),
                }
                for d, w in zip(drivers, weights, strict=True)
            ),
            key=lambda c: c["contribution_pct"],
            reverse=True,
        )
        return {
            **_key(geography, time_period, customer, sku),
            "method": "mock-shap",
            "drivers": contributions,
        }

    # Placeholders for agents that are switched off by default.
    @server.tool()
    def get_root_causes(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Root causes behind forecast misses (placeholder)."""
        return {**_key(geography, time_period, customer, sku), "root_causes": ["placeholder"]}

    @server.tool()
    def get_market_trends(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Market trends (placeholder)."""
        return {**_key(geography, time_period, customer, sku), "trends": ["placeholder"]}

    @server.tool()
    def get_market_recommendations(
        geography: Geography, time_period: TimePeriod, customer: Customer, sku: Sku
    ) -> dict[str, Any]:
        """Market recommendations (placeholder)."""
        return {**_key(geography, time_period, customer, sku), "recommendations": ["placeholder"]}

    return server
