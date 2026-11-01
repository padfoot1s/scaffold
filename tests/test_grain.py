import pytest

from inswa.grain import normalize_week
from inswa.orchestration.models import Slots


@pytest.mark.parametrize(
    "value", ["2026-W46", "2026W46", "2026-w46", "W46 2026", "Week 46, 2026", "2026-11-09", "2026-11-15"]
)
def test_week_formats_normalize_to_iso_week(value):
    assert normalize_week(value) == "2026-W46"


def test_year_boundary_uses_iso_year():
    assert normalize_week("2027-01-01") == "2026-W53"


def test_unparseable_week_counts_as_missing():
    slots = Slots(sku="1", primary_customer="Contoso", week="next Tuesday-ish")
    assert slots.week is None
    assert slots.missing(["sku", "primary_customer", "week"]) == ["week"]
