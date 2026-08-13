"""One-time Stripe catalogue setup, and the idempotency it promises.

`ensure_catalogue` is run by hand against a live account, which is the worst
possible place to discover a bug: creating a second "Osmos Pro" product means two
prices for the same thing, and customers silently split across them. Nothing in
the product would notice, and unpicking it afterwards means migrating live
subscriptions.

So its "run me twice, nothing happens" promise is worth pinning down here rather
than trusting a single trial run on an account that happened to be nearly empty.

The Stripe SDK is faked: these tests are about how the adapter *walks* the
account, and a real account cannot be given 150 products to prove the point.
"""
from __future__ import annotations

import pytest

from app.billing import stripe_client


class _Page:
    """Enough of a Stripe ListObject for the adapter to walk.

    Deliberately truthful about the thing being tested: `["data"]` returns only
    the first page, exactly as the real SDK does, while `auto_paging_iter()`
    walks everything. Code that reads `["data"]` therefore cannot see past the
    page boundary here either.
    """

    def __init__(self, items: list[dict], page_size: int = 100) -> None:
        self._items = list(items)
        self._page_size = page_size

    def __getitem__(self, key: str):
        if key != "data":
            raise KeyError(key)
        return self._items[: self._page_size]

    def auto_paging_iter(self):
        return iter(self._items)


class _FakeStripe:
    def __init__(self, products: list[dict], prices: list[dict]) -> None:
        self._products = products
        self._prices = prices
        self.created_products: list[dict] = []
        self.created_prices: list[dict] = []

        outer = self

        class Product:
            @staticmethod
            def list(**_kwargs):
                return _Page(outer._products)

            @staticmethod
            def create(**kwargs):
                created = {"id": f"prod_new_{len(outer.created_products)}", **kwargs}
                outer.created_products.append(created)
                outer._products.append(created)
                return created

        class Price:
            @staticmethod
            def list(**_kwargs):
                return _Page(outer._prices)

            @staticmethod
            def create(**kwargs):
                created = {"id": f"price_new_{len(outer.created_prices)}", **kwargs}
                outer.created_prices.append(created)
                outer._prices.append(created)
                return created

        self.Product = Product
        self.Price = Price


def _osmos_product() -> dict:
    return {
        "id": "prod_osmos",
        "name": "Osmos Pro",
        "metadata": {"osmos_catalogue": "pro"},
    }


def _price(price_id: str, amount: int, interval: str) -> dict:
    return {
        "id": price_id,
        "unit_amount": amount,
        "currency": "usd",
        "recurring": {"interval": interval},
        "metadata": {"osmos_catalogue": "pro"},
    }


@pytest.fixture
def fake(monkeypatch):
    def _install(products, prices):
        sdk = _FakeStripe(products, prices)
        monkeypatch.setattr(stripe_client, "_stripe", lambda: sdk)
        return sdk

    return _install


def test_a_second_run_creates_nothing(fake):
    """The whole promise of the script, on a tidy account."""
    sdk = fake(
        [_osmos_product()],
        [_price("price_m", 800, "month"), _price("price_y", 8400, "year")],
    )
    result = stripe_client.ensure_catalogue()

    assert sdk.created_products == []
    assert sdk.created_prices == []
    assert result["product_id"] == "prod_osmos"
    assert result["STRIPE_PRO_MONTHLY_PRICE_ID"] == "price_m"
    assert result["STRIPE_PRO_ANNUAL_PRICE_ID"] == "price_y"


def test_an_empty_account_gets_one_product_and_two_prices(fake):
    sdk = fake([], [])
    stripe_client.ensure_catalogue()

    assert len(sdk.created_products) == 1
    assert len(sdk.created_prices) == 2
    amounts = sorted(p["unit_amount"] for p in sdk.created_prices)
    assert amounts == [800, 8400]
    intervals = sorted(p["recurring"]["interval"] for p in sdk.created_prices)
    assert intervals == ["month", "year"]


def test_the_product_is_found_past_the_first_page_of_results(fake):
    """The bug this test exists for.

    Stripe's list endpoints cap at 100 per page. The adapter read only the first
    page, so on an account with more than 100 active products — an established
    business, or one that also sells something else — the existing "Osmos Pro"
    was invisible and a *duplicate* was created, along with a second pair of
    prices. Nothing surfaces that: the script prints ids and exits 0, and the
    account quietly has two products customers can be billed against.
    """
    filler = [
        {"id": f"prod_filler_{i}", "name": f"Other {i}", "metadata": {}}
        for i in range(150)
    ]
    sdk = fake(
        filler + [_osmos_product()],
        [_price("price_m", 800, "month"), _price("price_y", 8400, "year")],
    )
    result = stripe_client.ensure_catalogue()

    assert sdk.created_products == [], "created a duplicate Osmos Pro product"
    assert result["product_id"] == "prod_osmos"


def test_existing_prices_are_found_past_the_first_page(fake):
    """The same cap applies to prices, and a duplicate price is worse.

    Two active prices for the same interval means new subscribers are billed
    against a different price object from existing ones, which makes every
    later change — a rise, a discount, a currency — have to be done twice.
    """
    filler = [_price(f"price_filler_{i}", 1_00 + i, "month") for i in range(150)]
    sdk = fake(
        [_osmos_product()],
        filler + [_price("price_m", 800, "month"), _price("price_y", 8400, "year")],
    )
    result = stripe_client.ensure_catalogue()

    assert sdk.created_prices == [], "created duplicate seat prices"
    assert result["STRIPE_PRO_MONTHLY_PRICE_ID"] == "price_m"
    assert result["STRIPE_PRO_ANNUAL_PRICE_ID"] == "price_y"


def test_a_price_at_the_wrong_amount_is_not_reused(fake):
    """Matching is on amount and interval, so a stale price is left alone.

    If the monthly price were ever changed, the old object stays in the account.
    Reusing it by interval alone would quietly bill everyone the old amount.
    """
    sdk = fake([_osmos_product()], [_price("price_old", 500, "month")])
    result = stripe_client.ensure_catalogue()

    assert result["STRIPE_PRO_MONTHLY_PRICE_ID"] != "price_old"
    assert len(sdk.created_prices) == 2
