from datetime import date
from decimal import Decimal

from sales import kpis
from sales.checks import (
    KPI_COLUMNS,
    build_checks,
    evaluate_atv_identity,
    evaluate_sssg,
    evaluate_store_kpis,
)

BASE = kpis.BaseMeasures(10_000, 800, 200, 4_500, 2_000, 400, 900, 500)


def store_row(month=date(2026, 10, 1), open_date=date(2025, 9, 15), flag=True, tweak=0.0):
    expected = kpis.compute_kpis(BASE)
    values = [expected[k] for k in KPI_COLUMNS]
    values[KPI_COLUMNS.index("atv")] += tweak
    base = [Decimal(str(v)) for v in (10_000, 800, 200, 4_500, 2_000, 400, 900, 500)]
    return ("S005", month, open_date, flag, *base, *values)


def test_store_kpis_pass_when_view_matches_reference():
    passed, detail = evaluate_store_kpis([store_row()])
    assert passed, detail


def test_store_kpis_fail_on_formula_drift():
    passed, detail = evaluate_store_kpis([store_row(tweak=0.5)])
    assert not passed and "atv" in detail


def test_store_kpis_fail_on_wrong_comparable_flag():
    passed, detail = evaluate_store_kpis([store_row(month=date(2026, 9, 1), flag=True)])
    assert not passed and "is_comparable" in detail


def test_store_kpis_fail_when_empty():
    assert evaluate_store_kpis([])[0] is False


def test_sssg_check():
    month = date(2026, 10, 1)
    rows = [
        (month, "S001", date(2019, 3, 15), Decimal("110"), Decimal("100"), None),
        (month, "S006", date(2026, 3, 1), Decimal("50"), None, None),  # not comparable
    ]
    good = [(*r[:5], 0.1) for r in rows]
    assert evaluate_sssg(good)[0] is True
    bad = [(*r[:5], 0.2) for r in rows]
    assert evaluate_sssg(bad)[0] is False
    # Only months without SSSG at all -> fail (dataset too short for YoY).
    early = [(date(2025, 8, 1), "S001", date(2019, 3, 15), Decimal("1"), None, None)]
    assert evaluate_sssg(early)[0] is False


def test_atv_identity_check():
    assert evaluate_atv_identity([("North", date(2026, 1, 1), 22.5, 2.25, 10.0)])[0] is True
    assert evaluate_atv_identity([("North", date(2026, 1, 1), 23.0, 2.25, 10.0)])[0] is False
    assert evaluate_atv_identity([("North", date(2026, 1, 1), None, None, None)])[0] is True


def test_build_checks_targets_catalog_and_metric_views():
    checks = build_checks("prod", "silver", "gold")
    assert len({c.name for c in checks}) == len(checks)
    sql = "\n".join(c.sql for c in checks)
    assert "`prod`.`gold`.`sales_store_metrics`" in sql
    assert "`prod`.`gold`.`sales_category_metrics`" in sql
    assert "dev" not in sql
