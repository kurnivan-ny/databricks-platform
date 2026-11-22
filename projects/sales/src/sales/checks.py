"""Integration quality checks for the sales project (run as the last job task).

Besides row-count and integrity checks, the KPI checks recompute every KPI in Python
(sales.kpis) from the gold base measures and compare the results with what the
Unity Catalog metric views return. Metric-view formulas and the documented definitions
therefore cannot drift apart unnoticed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from platform_common.identifiers import qualified_name
from platform_common.quality import (
    Check,
    Row,
    close_enough,
    expect_at_most,
    expect_positive,
    expect_zero,
    to_float,
)

from sales import kpis

KPI_COLUMNS = (
    "net_sales",
    "gross_margin_pct",
    "sales_per_m2",
    "conversion_rate",
    "atv",
    "upt",
    "asp",
    "return_rate",
    "discount_rate",
)
MAX_QUARANTINE_SHARE = 0.01  # rejected lines must stay below 1% of valid lines


def _base(row: Sequence[object], offset: int) -> kpis.BaseMeasures:
    values = [to_float(v) or 0.0 for v in row[offset : offset + 8]]
    return kpis.BaseMeasures(*values)


def evaluate_store_kpis(rows: list[Row]) -> tuple[bool, str]:
    """Rows: store_id, month, open_date, is_comparable, 8 base measures, then the
    metric-view KPI values in KPI_COLUMNS order."""
    if not rows:
        return False, "no store-month rows returned"
    mismatches = []
    for row in rows:
        store_id, month, open_date, flag = row[0], row[1], row[2], row[3]
        expected = kpis.compute_kpis(_base(row, 4))
        actual = dict(zip(KPI_COLUMNS, (to_float(v) for v in row[12:]), strict=True))
        for kpi in KPI_COLUMNS:
            if not close_enough(expected[kpi], actual[kpi]):
                mismatches.append(
                    f"{store_id} {month} {kpi}: view={actual[kpi]} ref={expected[kpi]}"
                )
        if bool(flag) != kpis.is_comparable(_as_date(open_date), _as_date(month)):
            mismatches.append(f"{store_id} {month} is_comparable={flag} disagrees with reference")
    detail = f"{len(rows)} store-months compared"
    if mismatches:
        return False, f"{detail}; {len(mismatches)} mismatch(es): " + "; ".join(mismatches[:5])
    return True, detail


def evaluate_sssg(rows: list[Row]) -> tuple[bool, str]:
    """Rows: month, store_id, open_date, net_sales, net_sales_py, metric-view SSSG."""
    by_month: dict[object, list[kpis.StoreMonth]] = defaultdict(list)
    reported: dict[object, float | None] = {}
    for month, _store, open_date, net, net_py, view_sssg in rows:
        by_month[month].append(
            kpis.StoreMonth(
                kpis.is_comparable(_as_date(open_date), _as_date(month)),
                to_float(net) or 0.0,
                to_float(net_py),
            )
        )
        reported[month] = to_float(view_sssg)
    mismatches = [
        f"{m}: view={reported[m]} ref={kpis.same_store_sales_growth(group)}"
        for m, group in by_month.items()
        if not close_enough(reported[m], kpis.same_store_sales_growth(group))
    ]
    with_value = sum(v is not None for v in reported.values())
    if mismatches:
        return False, f"{len(mismatches)} month(s) differ: " + "; ".join(mismatches[:5])
    if not with_value:
        return False, "no month has a same-store sales growth value (need 13+ months of data)"
    return True, f"{len(by_month)} months compared, {with_value} with SSSG"


def evaluate_atv_identity(rows: list[Row]) -> tuple[bool, str]:
    """Rows: region, month, atv, upt, asp — ATV must equal UPT x ASP at any grain."""
    bad = [
        r
        for r in rows
        if None not in (to_float(r[2]), to_float(r[3]), to_float(r[4]))
        and not close_enough(to_float(r[2]), to_float(r[3]) * to_float(r[4]))  # type: ignore[operator]
    ]
    if bad:
        return False, f"{len(bad)} region-month(s) where ATV != UPT x ASP, e.g. {bad[0]}"
    return True, f"{len(rows)} region-months satisfy ATV = UPT x ASP"


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def build_checks(catalog: str, silver_schema: str, gold_schema: str) -> list[Check]:
    silver = lambda t: qualified_name(catalog, silver_schema, t)  # noqa: E731
    gold = lambda t: qualified_name(catalog, gold_schema, t)  # noqa: E731
    store_mv, category_mv = gold("sales_store_metrics"), gold("sales_category_metrics")
    kpi_select = ", ".join(f"MEASURE({k}) AS {k}" for k in KPI_COLUMNS)
    kpi_cols = ", ".join(f"mv.{k}" for k in KPI_COLUMNS)

    return [
        Check(
            "gold_store_monthly_not_empty",
            f"SELECT COUNT(*) FROM {gold('sales_store_monthly')}",
            expect_positive(),
        ),
        Check(
            "silver_lines_unique_key",
            "SELECT COUNT(*) - COUNT(DISTINCT txn_id, line_no) "
            f"FROM {silver('sales_transaction_lines')}",
            expect_zero(),
        ),
        Check(
            "quarantine_share_below_1pct",
            f"SELECT (SELECT COUNT(*) FROM {silver('sales_transaction_lines_quarantine')}) "
            f"/ (SELECT COUNT(*) FROM {silver('sales_transaction_lines')})",
            expect_at_most(MAX_QUARANTINE_SHARE),
        ),
        Check(
            "every_store_has_traffic_and_sales",
            f"SELECT COUNT(*) FROM {gold('sales_store_monthly')} "
            "WHERE traffic = 0 OR transactions = 0",
            expect_zero(),
        ),
        Check(
            "category_totals_reconcile_with_store_totals",
            f"SELECT ABS((SELECT SUM(net_sales) FROM {gold('sales_category_monthly')}) "
            f"- (SELECT SUM(net_sales) FROM {gold('sales_store_monthly')}))",
            expect_at_most(0.01),
        ),
        Check(
            "metric_view_net_sales_matches_gold",
            f"SELECT ABS((SELECT MEASURE(net_sales) FROM {store_mv}) "
            f"- (SELECT SUM(net_sales) FROM {gold('sales_store_monthly')}))",
            expect_at_most(0.01),
        ),
        Check(
            "category_metric_view_matches_gold",
            f"SELECT ABS((SELECT MEASURE(net_sales) FROM {category_mv}) "
            f"- (SELECT SUM(net_sales) FROM {gold('sales_category_monthly')}))",
            expect_at_most(0.01),
        ),
        Check(
            "store_kpis_match_python_reference",
            f"WITH mv AS (SELECT store_id, month, {kpi_select} FROM {store_mv} GROUP BY ALL) "
            "SELECT g.store_id, g.month, g.open_date, g.is_comparable, g.gross_sales, "
            "g.discounts, g.returns, g.cogs, g.traffic, g.transactions, g.units_sold, "
            f"g.selling_area_m2, {kpi_cols} "
            f"FROM {gold('sales_store_monthly')} AS g JOIN mv USING (store_id, month)",
            evaluate_store_kpis,
        ),
        Check(
            "sssg_matches_python_reference",
            f"WITH mv AS (SELECT month, MEASURE(same_store_sales_growth) AS sssg "
            f"FROM {store_mv} GROUP BY ALL) "
            "SELECT g.month, g.store_id, g.open_date, g.net_sales, g.net_sales_py, mv.sssg "
            f"FROM {gold('sales_store_monthly')} AS g JOIN mv USING (month)",
            evaluate_sssg,
        ),
        Check(
            "atv_equals_upt_times_asp",
            f"SELECT region, month, MEASURE(atv), MEASURE(upt), MEASURE(asp) "
            f"FROM {store_mv} GROUP BY ALL",
            evaluate_atv_identity,
        ),
    ]
