"""Pins the business KPI definitions agreed for the sales project."""

from datetime import date

import pytest
from sales.kpis import (
    BaseMeasures,
    StoreMonth,
    add_months,
    compute_kpis,
    first_full_month,
    is_comparable,
    point_change,
    safe_div,
    same_store_sales_growth,
    yoy_change,
)

MONTH = BaseMeasures(
    gross_sales=10_000.0,
    discounts=800.0,
    returns=200.0,
    cogs=4_500.0,
    traffic=2_000,
    transactions=400,
    units_sold=900,
    selling_area_m2=500,
)


def test_net_sales_is_gross_minus_discounts_minus_returns():
    assert MONTH.net_sales == 9_000.0


def test_kpi_formulas():
    k = compute_kpis(MONTH)
    assert k["gross_margin"] == 4_500.0
    assert k["gross_margin_pct"] == pytest.approx(0.5)
    assert k["sales_per_m2"] == pytest.approx(18.0)
    assert k["conversion_rate"] == pytest.approx(0.2)
    assert k["atv"] == pytest.approx(22.5)
    assert k["upt"] == pytest.approx(2.25)
    assert k["asp"] == pytest.approx(10.0)
    assert k["return_rate"] == pytest.approx(0.02)
    assert k["discount_rate"] == pytest.approx(0.08)


def test_atv_equals_upt_times_asp():
    k = compute_kpis(MONTH)
    assert k["atv"] == pytest.approx(k["upt"] * k["asp"])


def test_ratios_are_none_without_denominator():
    k = compute_kpis(BaseMeasures())
    assert all(k[name] is None for name in ("gross_margin_pct", "conversion_rate", "atv", "asp"))
    assert safe_div(1, 0) is None and safe_div(None, 1) is None


def test_measures_add_up_before_ratios():
    total = MONTH + BaseMeasures(gross_sales=1_000, transactions=100, traffic=1_000, units_sold=100)
    # Ratio of sums, not average of ratios.
    assert compute_kpis(total)["conversion_rate"] == pytest.approx(500 / 3_000)


@pytest.mark.parametrize(
    ("open_date", "first_full"),
    [
        (date(2025, 9, 15), date(2025, 10, 1)),
        (date(2026, 3, 1), date(2026, 3, 1)),
        (date(2024, 12, 31), date(2025, 1, 1)),
    ],
)
def test_first_full_month(open_date, first_full):
    assert first_full_month(open_date) == first_full


@pytest.mark.parametrize(
    ("open_date", "month", "expected"),
    [
        (date(2025, 9, 15), date(2026, 9, 1), False),  # only 11 full months
        (date(2025, 9, 15), date(2026, 10, 1), True),  # 12 full months (Oct 25 .. Sep 26)
        (date(2026, 3, 1), date(2027, 2, 1), False),
        (date(2026, 3, 1), date(2027, 3, 1), True),
        (date(2019, 3, 15), date(2025, 8, 1), True),
    ],
)
def test_comparable_store_rule(open_date, month, expected):
    assert is_comparable(open_date, month) is expected


def test_add_months():
    assert add_months(date(2026, 1, 1), -12) == date(2025, 1, 1)
    assert add_months(date(2025, 11, 1), 3) == date(2026, 2, 1)
    with pytest.raises(ValueError):
        add_months(date(2026, 1, 15), 1)


def test_sssg_uses_comparable_stores_with_prior_year_only():
    rows = [
        StoreMonth(True, 110.0, 100.0),
        StoreMonth(True, 210.0, 200.0),
        StoreMonth(False, 999.0, 1.0),  # new store: excluded
        StoreMonth(True, 50.0, None),  # no prior-year data: excluded
    ]
    assert same_store_sales_growth(rows) == pytest.approx(320 / 300 - 1)
    assert same_store_sales_growth([StoreMonth(False, 1.0, 1.0)]) is None


def test_yoy_and_point_changes():
    assert yoy_change(105.0, 100.0) == pytest.approx(0.05)
    assert yoy_change(1.0, 0.0) is None
    assert point_change(0.55, 0.52) == pytest.approx(0.03)
    assert point_change(None, 0.5) is None
