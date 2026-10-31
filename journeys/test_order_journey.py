import os, re
from pathlib import Path
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ["ORDER_APP_URL"]
RUN_ID = os.environ["RUN_ID"]
OUT = Path(os.environ["OUTDIR"])

def note(name: str, value: str) -> None:
    (OUT / f"{name}.txt").write_text(value)

def test_customer_can_place_order(page: Page) -> None:
    page.set_extra_http_headers({"x-drill-id": RUN_ID})
    note("step", "open-shop");   page.goto(BASE_URL)
    note("step", "add-to-cart"); page.get_by_test_id("product-SKU-001").get_by_test_id("add-to-cart").click()
    note("step", "checkout");    page.get_by_test_id("checkout").click()
    note("step", "place-order"); page.get_by_test_id("place-order").click()

    confirmation = page.get_by_test_id("confirmation-number")
    error = page.get_by_test_id("order-error")
    expect(confirmation.or_(error)).to_be_visible(timeout=20_000)
    if error.is_visible():
        note("error", error.inner_text())
        pytest.fail("order was not placed")

    number = confirmation.inner_text().strip()
    assert re.fullmatch(r"[A-Z0-9-]{6,}", number), number
    note("confirmation", number)
    note("step", "confirmed")
