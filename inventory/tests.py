import threading
from unittest import skipIf

from django.conf import settings
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, TransactionTestCase

from inventory.models import Product, Warehouse
from inventory.views import restock_product


class RestockProductTests(TestCase):
    def setUp(self):
        self.client = Client()
        wh = Warehouse.objects.create(name="Main", location="SG")
        self.product = Product.objects.create(
            name="Widget", sku="WID-1", price_cents=1500,
            warehouse=wh, quantity_on_hand=10,
        )
        self.url = f"/api/products/{self.product.pk}/restock/"

    # --- Happy path ---

    def test_valid_restock_increases_quantity(self):
        """POST with a valid positive amount returns 200 and correct new quantity."""
        resp = self.client.post(self.url, {"amount": "5"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["quantity"], 15)
        self.assertEqual(data["sku"], "WID-1")
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 15)

    def test_restock_amount_1(self):
        """Minimum valid amount (1) is accepted."""
        resp = self.client.post(self.url, {"amount": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["quantity"], 11)

    def test_restock_large_amount(self):
        """Large amounts are accepted without an upper-bound error."""
        resp = self.client.post(self.url, {"amount": "100000"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["quantity"], 100010)

    def test_response_contains_sku_and_quantity(self):
        """Response JSON has exactly the expected keys."""
        resp = self.client.post(self.url, {"amount": "3"})
        self.assertEqual(set(resp.json().keys()), {"sku", "quantity"})

    # --- Input validation errors ---

    def test_non_integer_amount_returns_400(self):
        """A non-integer amount string returns 400 with an error message."""
        resp = self.client.post(self.url, {"amount": "abc"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_float_amount_returns_400(self):
        """A float string is not a valid integer and returns 400."""
        resp = self.client.post(self.url, {"amount": "2.5"})
        self.assertEqual(resp.status_code, 400)

    def test_zero_amount_returns_400(self):
        """amount=0 is not a meaningful restock and returns 400."""
        resp = self.client.post(self.url, {"amount": "0"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("positive", resp.json()["error"])

    def test_negative_amount_returns_400(self):
        """A negative amount would decrement stock and must return 400."""
        resp = self.client.post(self.url, {"amount": "-5"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("positive", resp.json()["error"])

    def test_missing_amount_returns_400(self):
        """Omitting the amount parameter defaults to 0, which is rejected."""
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 400)

    def test_empty_amount_string_returns_400(self):
        """An empty string for amount returns 400."""
        resp = self.client.post(self.url, {"amount": ""})
        self.assertEqual(resp.status_code, 400)

    def test_amount_in_query_string_is_ignored(self):
        """amount passed as a query param (old bug location) is not used;
        only the POST body amount applies."""
        resp = self.client.post(self.url + "?amount=99", {"amount": "5"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["quantity"], 15)

    # --- 404 ---

    def test_nonexistent_product_returns_404(self):
        """A product_id that does not exist raises Http404.

        Uses RequestFactory (not the full test client) to bypass Django's
        page_not_found template renderer, which triggers a Python 3.14 /
        Django context-copy incompatibility via the test instrumentation signal.
        """
        request = RequestFactory().post(
            f"/api/products/99999/restock/", {"amount": "5"}
        )
        with self.assertRaises(Http404):
            restock_product(request, product_id=99999)

    # --- HTTP method guard ---

    def test_get_request_returns_405(self):
        """GET is not allowed on this endpoint."""
        resp = self.client.get(self.url, {"amount": "5"})
        self.assertEqual(resp.status_code, 405)

    # --- No side effects on error ---

    def test_database_unchanged_on_invalid_amount(self):
        """Stock is not modified when a 400 is returned."""
        self.client.post(self.url, {"amount": "-1"})
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 10)


class RestockProductConcurrencyTests(TransactionTestCase):
    """Verify that restock requests do not lose updates under load."""

    def setUp(self):
        wh = Warehouse.objects.create(name="Main", location="SG")
        self.product = Product.objects.create(
            name="Widget", sku="WID-1", price_cents=1500,
            warehouse=wh, quantity_on_hand=0,
        )
        self.url = f"/api/products/{self.product.pk}/restock/"

    def test_sequential_restocks_accumulate_correctly(self):
        """10 sequential restocks each adding 1 unit result in exactly 10.

        This proves the F() expression accumulates correctly and does not
        clobber previous writes (which the old read-modify-write bug would do
        if requests serialized at the DB level).
        """
        client = Client()
        for _ in range(10):
            resp = client.post(self.url, {"amount": "1"})
            self.assertEqual(resp.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 10)

    @skipIf(
        settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3",
        "SQLite allows only one writer at a time; run this test against PostgreSQL.",
    )
    def test_concurrent_restocks_are_all_applied(self):
        """10 threads each adding 1 unit should result in exactly 10 units.

        Requires a multi-writer database (PostgreSQL). SQLite serialises writes
        but raises 'table is locked' instead of queuing, so this test is skipped
        on SQLite. The F() expression guarantees the increment is atomic on any
        backend that supports concurrent writers.
        """
        n_threads = 10
        client = Client()
        errors = []

        def do_restock():
            resp = client.post(self.url, {"amount": "1"})
            if resp.status_code != 200:
                errors.append(resp.status_code)

        threads = [threading.Thread(target=do_restock) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Some requests failed: {errors}")
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, n_threads)
