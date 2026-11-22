"""Fictional store and product master data for the synthetic sales dataset.

Everything here is made up for the PoC; no real or production data is used.
Store open dates are chosen so the dataset contains all comparable-store situations:
long-standing stores, one store that becomes comparable during the data window
(S005, comparable from 2026-10) and one store that is never comparable (S006).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class Store:
    store_id: str
    store_name: str
    region: str
    city: str
    selling_area_m2: int
    open_date: date
    base_traffic: int  # average daily visitors before seasonality
    base_conversion: float  # share of visitors who buy

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["open_date"] = self.open_date.isoformat()
        del record["base_traffic"], record["base_conversion"]  # generator-only knobs
        return record


@dataclass(frozen=True)
class Product:
    product_id: str
    product_name: str
    category: str
    unit_price: float
    unit_cost: float
    popularity: float  # relative pick weight

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        del record["popularity"]
        return record


STORES: tuple[Store, ...] = (
    Store("S001", "Central Plaza", "North", "Northport", 1200, date(2019, 3, 15), 300, 0.24),
    Store("S002", "Riverside", "North", "Northport", 650, date(2021, 6, 1), 190, 0.22),
    Store("S003", "Harbor Point", "South", "Southbay", 900, date(2020, 9, 10), 250, 0.23),
    Store("S004", "Old Town", "East", "Eastfield", 480, date(2022, 11, 20), 160, 0.26),
    Store("S005", "Lakeside Mall", "West", "Westlake", 1000, date(2025, 9, 15), 230, 0.21),
    Store("S006", "Airport Outlet", "South", "Southbay", 550, date(2026, 3, 1), 170, 0.20),
)

PRODUCTS: tuple[Product, ...] = (
    Product("P001", "Classic Tee", "Apparel", 19.90, 7.50, 9.0),
    Product("P002", "Slim Jeans", "Apparel", 59.90, 24.00, 6.0),
    Product("P003", "Hooded Sweatshirt", "Apparel", 44.90, 17.00, 5.0),
    Product("P004", "Rain Jacket", "Apparel", 89.90, 38.00, 2.5),
    Product("P005", "Linen Shirt", "Apparel", 39.90, 15.50, 4.0),
    Product("P006", "Running Shoe", "Footwear", 99.90, 52.00, 3.5),
    Product("P007", "Canvas Sneaker", "Footwear", 54.90, 26.00, 4.5),
    Product("P008", "Leather Boot", "Footwear", 129.90, 68.00, 1.5),
    Product("P009", "Sandal", "Footwear", 29.90, 13.00, 3.0),
    Product("P010", "Leather Belt", "Accessories", 24.90, 8.00, 3.5),
    Product("P011", "Wool Scarf", "Accessories", 22.90, 7.00, 3.0),
    Product("P012", "Backpack", "Accessories", 49.90, 21.00, 2.5),
    Product("P013", "Sunglasses", "Accessories", 34.90, 9.50, 2.5),
    Product("P014", "Face Cream", "Beauty", 18.90, 4.80, 5.0),
    Product("P015", "Shampoo", "Beauty", 8.90, 2.60, 7.0),
    Product("P016", "Eau de Parfum", "Beauty", 64.90, 19.00, 1.5),
    Product("P017", "Lip Balm", "Beauty", 4.90, 1.20, 6.0),
    Product("P018", "Scented Candle", "Home", 16.90, 7.80, 4.0),
    Product("P019", "Cotton Towel", "Home", 14.90, 7.20, 4.5),
    Product("P020", "Ceramic Mug", "Home", 9.90, 4.40, 5.0),
    Product("P021", "Throw Blanket", "Home", 39.90, 21.00, 2.0),
)
