import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from catalog import PRODUCTS  # noqa: E402

SEED_SQL = Path(__file__).resolve().parents[3] / "sql" / "seed.sql"
SEED_ROW = re.compile(r"\('(SKU-\d+)',\s*N'([^']*)',\s*([\d.]+)\)")


def _seed_products():
    rows = SEED_ROW.findall(SEED_SQL.read_text(encoding="utf-8"))
    return {sku: {"sku": sku, "name": name, "price": float(price)} for sku, name, price in rows}


def test_catalog_matches_seed_sql():
    seed = _seed_products()
    assert seed, "no product rows found in sql/seed.sql"
    assert PRODUCTS == seed


def test_each_product_is_keyed_by_its_own_sku():
    for sku, product in PRODUCTS.items():
        assert product["sku"] == sku
        assert product["price"] > 0
