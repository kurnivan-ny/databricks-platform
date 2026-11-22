"""Deterministic synthetic POS + footfall data for the sales PoC.

Output is newline-delimited JSON, one file per dataset per business day::

    <landing>/stores/stores.json                       (reference data, overwritten)
    <landing>/products/products.json                   (reference data, overwritten)
    <landing>/traffic/traffic_<YYYY-MM-DD>.json        (door-counter visitors per store)
    <landing>/transactions/transactions_<YYYY-MM-DD>.json  (receipts with nested lines)

Generation is a pure function of (seed, store, date), so re-running a day reproduces the
same bytes. The job only writes days whose transactions file is missing, which makes
backfill + daily increments idempotent and keeps Auto Loader from ingesting duplicates.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sales.reference_data import PRODUCTS, STORES, Product, Store

DOW_FACTOR = (0.85, 0.85, 0.90, 0.95, 1.10, 1.40, 1.20)  # Monday..Sunday
MONTH_FACTOR = (0.85, 0.80, 0.90, 0.95, 1.00, 1.00, 1.05, 1.00, 0.95, 1.00, 1.15, 1.45)
ANNUAL_GROWTH = 0.04
GROWTH_BASE_DATE = date(2025, 1, 1)
RAMP_UP_DAYS = 90  # new stores reach full traffic after ~3 months
TRAFFIC_NOISE = 0.08
CONVERSION_NOISE = 0.02
LINE_COUNT_WEIGHTS = ((1, 0.42), (2, 0.30), (3, 0.16), (4, 0.08), (5, 0.04))
MULTI_UNIT_SHARE = 0.12
DISCOUNT_LINE_SHARE = 0.22
DISCOUNT_RATES = (0.10, 0.20, 0.30)
RETURN_SHARE = 0.035
OPEN_HOUR, CLOSE_HOUR = 9, 21

DATASETS = ("traffic", "transactions")
COMPLETION_MARKER = "transactions"  # written last; its presence means the day is complete


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 42
    bad_record_rate: float = 0.001  # share of receipts duplicated as invalid records


def _rng(seed: int, *parts: object) -> random.Random:
    # String seeds are hashed with SHA-512 by random.Random, so this is stable across runs.
    return random.Random("|".join(str(p) for p in (seed, *parts)))


def is_open(store: Store, day: date) -> bool:
    return day >= store.open_date


def expected_traffic(store: Store, day: date) -> float:
    if not is_open(store, day):
        return 0.0
    years = (day - GROWTH_BASE_DATE).days / 365.25
    growth = (1 + ANNUAL_GROWTH) ** years
    ramp = min(1.0, 0.6 + 0.4 * (day - store.open_date).days / RAMP_UP_DAYS)
    seasonality = DOW_FACTOR[day.weekday()] * MONTH_FACTOR[day.month - 1]
    return store.base_traffic * seasonality * growth * ramp


def generate_traffic(store: Store, day: date, config: GeneratorConfig) -> dict | None:
    if not is_open(store, day):
        return None
    rng = _rng(config.seed, "traffic", store.store_id, day.isoformat())
    mean = expected_traffic(store, day)
    visitors = max(0, round(rng.gauss(mean, mean * TRAFFIC_NOISE)))
    return {"store_id": store.store_id, "business_date": day.isoformat(), "visitors": visitors}


def _pick_line_count(rng: random.Random) -> int:
    counts, weights = zip(*LINE_COUNT_WEIGHTS, strict=True)
    return rng.choices(counts, weights=weights)[0]


def _sale(rng: random.Random, store: Store, day: date, seq: int) -> dict:
    opened = datetime.combine(day, time(OPEN_HOUR))
    ts = opened + timedelta(seconds=rng.randrange((CLOSE_HOUR - OPEN_HOUR) * 3600))
    weights = [p.popularity for p in PRODUCTS]
    lines = []
    for line_no in range(1, _pick_line_count(rng) + 1):
        product: Product = rng.choices(PRODUCTS, weights=weights)[0]
        quantity = 2 if rng.random() < MULTI_UNIT_SHARE else 1
        gross = round(product.unit_price * quantity, 2)
        discount = (
            round(gross * rng.choice(DISCOUNT_RATES), 2)
            if rng.random() < DISCOUNT_LINE_SHARE
            else 0.0
        )
        lines.append(
            {
                "line_no": line_no,
                "product_id": product.product_id,
                "quantity": quantity,
                "unit_price": product.unit_price,
                "discount_amount": discount,
                "unit_cost": product.unit_cost,
            }
        )
    return {
        "txn_id": f"{store.store_id}-{day:%Y%m%d}-S{seq:05d}",
        "store_id": store.store_id,
        "business_date": day.isoformat(),
        "txn_ts": ts.isoformat(),
        "txn_type": "SALE",
        "original_txn_id": None,
        "lines": lines,
    }


def _return(rng: random.Random, sale: dict, seq: int) -> dict:
    """Same-day return of one full line of ``sale`` (refund = the line's net amount)."""
    sale_ts = datetime.fromisoformat(sale["txn_ts"])
    closing = datetime.combine(sale_ts.date(), time(CLOSE_HOUR))
    ts = min(closing, sale_ts + timedelta(minutes=rng.randrange(10, 240)))
    returned_line = dict(rng.choice(sale["lines"]), line_no=1)
    return {
        "txn_id": sale["txn_id"].rsplit("-", 1)[0] + f"-R{seq:05d}",
        "store_id": sale["store_id"],
        "business_date": sale["business_date"],
        "txn_ts": ts.isoformat(),
        "txn_type": "RETURN",
        "original_txn_id": sale["txn_id"],
        "lines": [returned_line],
    }


def generate_transactions(
    store: Store, day: date, visitors: int, config: GeneratorConfig
) -> list[dict]:
    rng = _rng(config.seed, "transactions", store.store_id, day.isoformat())
    conversion = min(0.6, max(0.05, rng.gauss(store.base_conversion, CONVERSION_NOISE)))
    buyers = sum(1 for _ in range(visitors) if rng.random() < conversion)
    sales = [_sale(rng, store, day, seq) for seq in range(1, buyers + 1)]

    returns = []
    for sale in sales:
        if rng.random() < RETURN_SHARE:
            returns.append(_return(rng, sale, len(returns) + 1))

    # A few deliberately invalid records exercise the silver-layer expectations.
    invalid = []
    for sale in sales:
        if rng.random() < config.bad_record_rate:
            bad = dict(sale, txn_id=sale["txn_id"].replace("-S", "-X"), store_id=None)
            invalid.append(bad)
    return sales + returns + invalid


def to_ndjson(records: Iterable[dict]) -> str:
    return "".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n" for r in records)


def day_filename(dataset: str, day: date) -> str:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    return f"{dataset}_{day.isoformat()}.json"


def build_day_files(
    day: date, config: GeneratorConfig, stores: Sequence[Store] = STORES
) -> dict[str, str]:
    """Return ``{dataset: ndjson_text}`` for one business day across all stores."""
    traffic, transactions = [], []
    for store in stores:
        record = generate_traffic(store, day, config)
        if record is None:
            continue
        traffic.append(record)
        transactions.extend(generate_transactions(store, day, record["visitors"], config))
    return {"traffic": to_ndjson(traffic), "transactions": to_ndjson(transactions)}


def reference_files() -> dict[str, str]:
    return {
        "stores": to_ndjson(s.to_record() for s in STORES),
        "products": to_ndjson(p.to_record() for p in PRODUCTS),
    }


def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from ``start`` to ``end`` (empty if end < start)."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def missing_dates(existing_filenames: Iterable[str], start: date, end: date) -> list[date]:
    """Dates in [start, end] whose completion-marker file does not exist yet."""
    existing = set(existing_filenames)
    return [d for d in date_range(start, end) if day_filename(COMPLETION_MARKER, d) not in existing]
