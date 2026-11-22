"""Reference implementation of the sales KPI definitions (see docs/kpi-definitions.md).

The production formulas live in the Unity Catalog metric views
(src/metric_views/*.yaml). This module restates them in plain Python so that:

* unit tests document and pin the business definitions, and
* the integration quality checks can recompute KPIs independently from the gold
  base measures and compare them with what the metric views return.

Keep the two in sync: a definition change must update both, plus the docs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import date

COMPARABLE_AFTER_FULL_MONTHS = 12


@dataclass(frozen=True)
class BaseMeasures:
    """Additive measures for any slice (store-month, region-month, total, ...)."""

    gross_sales: float = 0.0
    discounts: float = 0.0
    returns: float = 0.0
    cogs: float = 0.0
    traffic: float = 0.0
    transactions: float = 0.0
    units_sold: float = 0.0
    selling_area_m2: float = 0.0  # summed per store-month row

    def __add__(self, other: BaseMeasures) -> BaseMeasures:
        return BaseMeasures(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )

    @property
    def net_sales(self) -> float:
        """Net sales = gross sales - discounts - returns (excluding VAT)."""
        return self.gross_sales - self.discounts - self.returns


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def compute_kpis(m: BaseMeasures) -> dict[str, float | None]:
    net = m.net_sales
    gross_margin = net - m.cogs
    return {
        "net_sales": net,
        "gross_margin": gross_margin,
        "gross_margin_pct": safe_div(gross_margin, net),
        "sales_per_m2": safe_div(net, m.selling_area_m2),
        "traffic": m.traffic,
        "transactions": m.transactions,
        "conversion_rate": safe_div(m.transactions, m.traffic),
        "atv": safe_div(net, m.transactions),
        "upt": safe_div(m.units_sold, m.transactions),
        "asp": safe_div(net, m.units_sold),
        "return_rate": safe_div(m.returns, m.gross_sales),
        "discount_rate": safe_div(m.discounts, m.gross_sales),
    }


def add_months(month_start: date, months: int) -> date:
    """Shift a first-of-month date by ``months`` (result is also a first-of-month)."""
    if month_start.day != 1:
        raise ValueError(f"{month_start} is not the first day of a month")
    index = month_start.year * 12 + (month_start.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def first_full_month(open_date: date) -> date:
    """First calendar month the store traded for the whole month."""
    month = open_date.replace(day=1)
    return month if open_date.day == 1 else add_months(month, 1)


def is_comparable(
    open_date: date, month_start: date, full_months: int = COMPARABLE_AFTER_FULL_MONTHS
) -> bool:
    """A store is comparable in a month once it has traded ``full_months`` full months
    before that month (e.g. opened 2025-09-15 -> first full month 2025-10 -> comparable
    from 2026-10)."""
    return add_months(first_full_month(open_date), full_months) <= month_start


@dataclass(frozen=True)
class StoreMonth:
    is_comparable: bool
    net_sales: float
    net_sales_py: float | None  # same store, same month last year (like-for-like days)


def same_store_sales_growth(rows: Iterable[StoreMonth]) -> float | None:
    """SSSG = comparable stores' net sales / their net sales same period last year - 1.

    Only comparable stores with prior-year data are included, on both sides.
    """
    current = prior = 0.0
    for row in rows:
        if row.is_comparable and row.net_sales_py is not None:
            current += row.net_sales
            prior += row.net_sales_py
    ratio = safe_div(current, prior)
    return None if ratio is None else ratio - 1


def yoy_change(current: float | None, prior: float | None) -> float | None:
    """Relative change vs last year (e.g. 0.05 = +5%)."""
    ratio = safe_div(current, prior)
    return None if ratio is None else ratio - 1


def point_change(current: float | None, prior: float | None) -> float | None:
    """Absolute change for rates (e.g. margin 0.52 -> 0.55 = +0.03 = +3 pts)."""
    if current is None or prior is None:
        return None
    return current - prior
