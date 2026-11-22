import json
from datetime import date

from sales import generator
from sales.generator import GeneratorConfig, build_day_files, missing_dates
from sales.reference_data import PRODUCTS, STORES

DAY = date(2026, 6, 13)  # a Saturday
CONFIG = GeneratorConfig()


def records(text):
    return [json.loads(line) for line in text.splitlines()]


def test_generation_is_deterministic():
    assert build_day_files(DAY, CONFIG) == build_day_files(DAY, CONFIG)
    assert build_day_files(DAY, GeneratorConfig(seed=7)) != build_day_files(DAY, CONFIG)


def test_stores_trade_only_after_opening():
    before = records(build_day_files(date(2026, 2, 28), CONFIG)["traffic"])
    after = records(build_day_files(date(2026, 3, 1), CONFIG)["traffic"])
    assert "S006" not in {r["store_id"] for r in before}
    assert "S006" in {r["store_id"] for r in after}


def test_transactions_are_consistent():
    files = build_day_files(DAY, CONFIG)
    traffic = {r["store_id"]: r["visitors"] for r in records(files["traffic"])}
    txns = records(files["transactions"])
    ids = [t["txn_id"] for t in txns]
    assert len(ids) == len(set(ids)), "transaction ids must be unique"

    sales = [t for t in txns if t["txn_type"] == "SALE" and t["store_id"]]
    for store_id, visitors in traffic.items():
        buyers = sum(1 for t in sales if t["store_id"] == store_id)
        assert 0.05 <= buyers / visitors <= 0.6

    sale_ids = {t["txn_id"] for t in sales}
    for ret in (t for t in txns if t["txn_type"] == "RETURN"):
        assert ret["original_txn_id"] in sale_ids
        assert len(ret["lines"]) == 1

    for txn in txns:
        for line in txn["lines"]:
            gross = round(line["unit_price"] * line["quantity"], 2)
            assert 0 <= line["discount_amount"] <= gross
            assert line["quantity"] > 0


def test_invalid_records_are_flagged_for_quarantine():
    txns = records(build_day_files(DAY, GeneratorConfig(bad_record_rate=0.05))["transactions"])
    invalid = [t for t in txns if t["store_id"] is None]
    assert invalid and all("-X" in t["txn_id"] for t in invalid)
    clean = records(build_day_files(DAY, GeneratorConfig(bad_record_rate=0.0))["transactions"])
    assert all(t["store_id"] for t in clean)


def test_seasonality_weekend_busier_than_weekday():
    store = STORES[0]
    assert generator.expected_traffic(store, date(2026, 6, 13)) > generator.expected_traffic(
        store, date(2026, 6, 9)
    )


def test_reference_files_hide_generator_knobs():
    ref = generator.reference_files()
    stores = records(ref["stores"])
    assert len(stores) == len(STORES)
    assert set(stores[0]) == {
        "store_id",
        "store_name",
        "region",
        "city",
        "selling_area_m2",
        "open_date",
    }
    products = records(ref["products"])
    assert len(products) == len(PRODUCTS)
    assert all(p["unit_cost"] < p["unit_price"] for p in products)


def test_missing_dates_uses_completion_marker():
    existing = ["transactions_2026-01-01.json", "traffic_2026-01-02.json"]
    assert missing_dates(existing, date(2026, 1, 1), date(2026, 1, 3)) == [
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert missing_dates([], date(2026, 1, 2), date(2026, 1, 1)) == []
