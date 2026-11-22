from decimal import Decimal

import pytest
from platform_common.quality import (
    Check,
    QualityCheckError,
    assert_all_passed,
    close_enough,
    expect_at_most,
    expect_positive,
    expect_zero,
    format_report,
    run_checks,
    scalar,
    to_float,
)


def test_expectations():
    assert expect_zero()([(0,)])[0] is True
    assert expect_zero()([(3,)])[0] is False
    assert expect_positive()([(Decimal("1.5"),)])[0] is True
    assert expect_positive()([(None,)])[0] is False
    assert expect_at_most(0.01)([(0.01,)])[0] is True
    assert expect_at_most(0.01)([(0.02,)])[0] is False


def test_scalar_requires_single_value():
    with pytest.raises(ValueError):
        scalar([(1, 2)])
    with pytest.raises(ValueError):
        scalar([])


def test_run_checks_reports_errors_without_aborting():
    def query(sql):
        if sql == "boom":
            raise RuntimeError("table not found")
        return [(0,)]

    checks = [Check("a", "boom", expect_zero()), Check("b", "ok", expect_zero())]
    results = run_checks(checks, query)
    assert [r.passed for r in results] == [False, True]
    assert "table not found" in results[0].detail
    assert "1/2 checks passed" in format_report(results)


def test_assert_all_passed_raises_with_report():
    results = run_checks([Check("a", "x", expect_positive())], lambda sql: [(0,)])
    with pytest.raises(QualityCheckError, match=r"\[FAIL\] a"):
        assert_all_passed(results)


def test_numeric_helpers():
    assert to_float(Decimal("2.50")) == 2.5
    assert to_float(None) is None
    assert close_enough(1.0, 1.0 + 1e-9)
    assert not close_enough(1.0, 1.01)
    assert close_enough(None, None)
    assert not close_enough(None, 0.0)
