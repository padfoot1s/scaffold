"""Forecast grain: SKU x primary customer x ISO week (`YYYY-Www`, weeks start on Monday)."""

from __future__ import annotations

import re
from datetime import date, timedelta

_ISO_WEEK = re.compile(r"^\s*(\d{4})\s*-?\s*W\s*(\d{1,2})\s*$", re.IGNORECASE)
_WEEK_FIRST = re.compile(r"^\s*W(?:eek)?\s*(\d{1,2})\s*,?\s*(\d{4})\s*$", re.IGNORECASE)


def parse_week(value: str) -> date:
    """Monday of the ISO week given as `2026-W46`, `2026W46`, `W46 2026` or any ISO date in that week."""
    if match := _ISO_WEEK.match(value) or _WEEK_FIRST.match(value):
        year, week = match.groups() if match.re is _ISO_WEEK else reversed(match.groups())
        return date.fromisocalendar(int(year), int(week), 1)
    day = date.fromisoformat(value.strip())
    return day - timedelta(days=day.weekday())


def normalize_week(value: str) -> str:
    """Canonical `YYYY-Www`; raises ValueError for anything that is not a week or date."""
    year, week, _ = parse_week(value).isocalendar()
    return f"{year}-W{week:02d}"


def week_label(monday: date) -> str:
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"
