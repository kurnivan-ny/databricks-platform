"""Minimal data-quality check runner used by integration-test job tasks.

A check is a SQL statement plus a pure ``evaluate`` function over the returned rows.
The query function is injected, so the same checks run against Spark inside a job and
against fakes in local unit tests.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Row = Sequence[object]
QueryFn = Callable[[str], list[Row]]
Evaluator = Callable[[list[Row]], tuple[bool, str]]


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    evaluate: Evaluator
    description: str = ""


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


class QualityCheckError(AssertionError):
    """Raised when one or more checks fail; the message is the full report."""


def to_float(value: object) -> float | None:
    """Convert Decimal/int/float/None from a SQL row into float (or None)."""
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]


def close_enough(a: float | None, b: float | None, tolerance: float = 1e-6) -> bool:
    """Compare two optional numbers with a combined relative/absolute tolerance."""
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)


def scalar(rows: list[Row]) -> object:
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError(f"expected exactly one row with one column, got {len(rows)} row(s)")
    return rows[0][0]


def expect_scalar(predicate: Callable[[float], bool], expectation: str) -> Evaluator:
    def evaluate(rows: list[Row]) -> tuple[bool, str]:
        value = to_float(scalar(rows))
        passed = value is not None and predicate(value)
        return passed, f"value={value} (expected {expectation})"

    return evaluate


def expect_zero() -> Evaluator:
    return expect_scalar(lambda v: v == 0, "== 0")


def expect_positive() -> Evaluator:
    return expect_scalar(lambda v: v > 0, "> 0")


def expect_at_most(limit: float) -> Evaluator:
    return expect_scalar(lambda v: v <= limit, f"<= {limit}")


def run_checks(checks: Sequence[Check], query: QueryFn) -> list[CheckResult]:
    """Run every check; a query/evaluation error counts as a failure, never aborts the run."""
    results = []
    for check in checks:
        try:
            passed, detail = check.evaluate(query(check.sql))
        except Exception as exc:  # report and continue with the remaining checks
            passed, detail = False, f"error: {type(exc).__name__}: {exc}"
        results.append(CheckResult(check.name, passed, detail))
    return results


def format_report(results: Sequence[CheckResult]) -> str:
    lines = [f"[{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}" for r in results]
    failed = sum(not r.passed for r in results)
    lines.append(f"{len(results) - failed}/{len(results)} checks passed")
    return "\n".join(lines)


def assert_all_passed(results: Sequence[CheckResult]) -> None:
    if any(not r.passed for r in results):
        raise QualityCheckError(format_report(results))
