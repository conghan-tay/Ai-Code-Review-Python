import threading
from unittest import skipIf

from django.conf import settings
from django.contrib.auth.models import User
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, TransactionTestCase

from inventory.models import Order, OrderItem, Product, Warehouse
from inventory.views import order_summary, place_order, restock_product


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


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(username="alice")
        wh = Warehouse.objects.create(name="Main", location="SG")
        self.p1 = Product.objects.create(
            name="Widget", sku="WID-1", price_cents=1500,
            warehouse=wh, quantity_on_hand=5,
        )
        self.p2 = Product.objects.create(
            name="Gadget", sku="GAD-1", price_cents=4200,
            warehouse=wh, quantity_on_hand=2,
        )
        self.url = f"/api/customers/{self.user.pk}/place-order/"

    # --- Happy path ---

    def test_single_product_creates_paid_order(self):
        """One product_id decrements stock by 1 and creates a paid order with one line."""
        resp = self.client.post(self.url, {"product_id": [str(self.p1.pk)]})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("order_id", data)
        self.assertIn("total_cents", data)

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 4)

        order = Order.objects.get(pk=data["order_id"])
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(order.customer_id, self.user.pk)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(data["total_cents"], 1500)

    def test_multiple_distinct_products(self):
        """Each distinct product is decremented once; total reflects all line prices."""
        resp = self.client.post(
            self.url, {"product_id": [str(self.p1.pk), str(self.p2.pk)]}
        )
        self.assertEqual(resp.status_code, 200)

        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 4)
        self.assertEqual(self.p2.quantity_on_hand, 1)

        order = Order.objects.get(pk=resp.json()["order_id"])
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(resp.json()["total_cents"], 1500 + 4200)

    def test_same_product_listed_twice_decrements_twice(self):
        """Repeating a product_id produces two line items and decrements stock by 2."""
        resp = self.client.post(
            self.url, {"product_id": [str(self.p1.pk), str(self.p1.pk)]}
        )
        self.assertEqual(resp.status_code, 200)

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 3)

        order = Order.objects.get(pk=resp.json()["order_id"])
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(resp.json()["total_cents"], 1500 * 2)

    def test_order_at_exact_remaining_stock(self):
        """A product with qty=1 can be ordered exactly once, leaving qty=0."""
        self.p1.quantity_on_hand = 1
        self.p1.save()

        resp = self.client.post(self.url, {"product_id": [str(self.p1.pk)]})
        self.assertEqual(resp.status_code, 200)

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 0)

    def test_response_keys(self):
        """Response JSON has exactly the expected keys on success."""
        resp = self.client.post(self.url, {"product_id": [str(self.p1.pk)]})
        self.assertEqual(set(resp.json().keys()), {"order_id", "total_cents"})

    # --- Stock errors (atomic rollback) ---

    def test_out_of_stock_returns_409(self):
        """Ordering a product with qty=0 returns 409 and creates no order."""
        self.p1.quantity_on_hand = 0
        self.p1.save()

        resp = self.client.post(self.url, {"product_id": [str(self.p1.pk)]})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("out of stock", resp.json()["error"])

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 0)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_one_product_out_of_stock_rolls_back_others(self):
        """If a later product is out of stock, earlier decrements are rolled back."""
        self.p2.quantity_on_hand = 0
        self.p2.save()

        resp = self.client.post(
            self.url, {"product_id": [str(self.p1.pk), str(self.p2.pk)]}
        )
        self.assertEqual(resp.status_code, 409)

        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 5)
        self.assertEqual(self.p2.quantity_on_hand, 0)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_buying_more_than_stock_in_single_order(self):
        """Listing a product more times than its stock fails the whole order."""
        self.p1.quantity_on_hand = 1
        self.p1.save()

        resp = self.client.post(
            self.url, {"product_id": [str(self.p1.pk), str(self.p1.pk)]}
        )
        self.assertEqual(resp.status_code, 409)

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 1)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    # --- Not-found ---

    def test_nonexistent_product_returns_404(self):
        """An unknown product_id returns 404 and leaves stock of valid products untouched."""
        resp = self.client.post(
            self.url, {"product_id": [str(self.p1.pk), "99999"]}
        )
        self.assertEqual(resp.status_code, 404)

        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity_on_hand, 5)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_nonexistent_customer_returns_404(self):
        """An unknown customer_id raises Http404.

        Uses RequestFactory to bypass Django's page_not_found template renderer
        (same reason as test_nonexistent_product_returns_404 in RestockProductTests).
        """
        request = RequestFactory().post(
            "/api/customers/99999/place-order/", {"product_id": [str(self.p1.pk)]}
        )
        with self.assertRaises(Http404):
            place_order(request, customer_id=99999)

    # --- HTTP method guard ---

    def test_get_request_returns_405(self):
        """GET is not allowed on this endpoint."""
        resp = self.client.get(self.url, {"product_id": [str(self.p1.pk)]})
        self.assertEqual(resp.status_code, 405)


class PlaceOrderConcurrencyTests(TransactionTestCase):
    """Verify that place_order does not oversell stock under load."""

    def setUp(self):
        self.user = User.objects.create(username="alice")
        wh = Warehouse.objects.create(name="Main", location="SG")
        self.product = Product.objects.create(
            name="Widget", sku="WID-1", price_cents=1500,
            warehouse=wh, quantity_on_hand=0,
        )
        self.url = f"/api/customers/{self.user.pk}/place-order/"

    def test_sequential_orders_decrement_correctly(self):
        """10 sequential orders against qty=10 each succeed; stock ends at 0."""
        self.product.quantity_on_hand = 10
        self.product.save()

        client = Client()
        for _ in range(10):
            resp = client.post(self.url, {"product_id": [str(self.product.pk)]})
            self.assertEqual(resp.status_code, 200)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 0)
        self.assertEqual(Order.objects.filter(customer=self.user).count(), 10)

    @skipIf(
        settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3",
        "SQLite allows only one writer at a time; run this test against PostgreSQL.",
    )
    def test_concurrent_orders_do_not_oversell(self):
        """10 threads each placing 1 order against qty=10 → all succeed, stock=0.

        Direct regression test for the read-modify-write race that the
        select_for_update + transaction.atomic fix closes.
        """
        self.product.quantity_on_hand = 10
        self.product.save()

        n_threads = 10
        client = Client()
        statuses = []
        lock = threading.Lock()

        def do_order():
            resp = client.post(self.url, {"product_id": [str(self.product.pk)]})
            with lock:
                statuses.append(resp.status_code)

        threads = [threading.Thread(target=do_order) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(
            statuses.count(200), n_threads,
            f"Expected all orders to succeed, got statuses {statuses}",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 0)
        self.assertEqual(Order.objects.filter(customer=self.user).count(), n_threads)

    @skipIf(
        settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3",
        "SQLite allows only one writer at a time; run this test against PostgreSQL.",
    )
    def test_concurrent_orders_exceeding_stock_partial_success(self):
        """10 threads contending for qty=3 → exactly 3 succeed, 7 get 409, stock=0.

        Proves select_for_update serialises stock reads under contention and that
        failed orders roll back cleanly without persisting partial OrderItems.
        """
        self.product.quantity_on_hand = 3
        self.product.save()

        n_threads = 10
        client = Client()
        statuses = []
        lock = threading.Lock()

        def do_order():
            resp = client.post(self.url, {"product_id": [str(self.product.pk)]})
            with lock:
                statuses.append(resp.status_code)

        threads = [threading.Thread(target=do_order) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(statuses.count(200), 3, f"statuses={statuses}")
        self.assertEqual(statuses.count(409), 7, f"statuses={statuses}")

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_on_hand, 0)
        self.assertEqual(Order.objects.filter(customer=self.user).count(), 3)
        self.assertEqual(OrderItem.objects.count(), 3)


class OrderSummaryTests(TestCase):
    # Expected DB queries per request: 1 for User existence check, 1 for orders,
    # 1 for the prefetched items joined with product and warehouse.
    EXPECTED_QUERIES = 3

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(username="alice")
        self.other_user = User.objects.create(username="bob")

        self.wh1 = Warehouse.objects.create(name="Main", location="SG")
        self.wh2 = Warehouse.objects.create(name="Backup", location="MY")

        self.p1 = Product.objects.create(
            name="Widget", sku="WID-1", price_cents=1500,
            warehouse=self.wh1, quantity_on_hand=50,
        )
        self.p2 = Product.objects.create(
            name="Gadget", sku="GAD-1", price_cents=4200,
            warehouse=self.wh1, quantity_on_hand=50,
        )
        self.p3 = Product.objects.create(
            name="Gizmo", sku="GIZ-1", price_cents=999,
            warehouse=self.wh2, quantity_on_hand=50,
        )

        self.order_a = Order.objects.create(
            customer=self.user, status=Order.STATUS_PAID,
        )
        OrderItem.objects.create(order=self.order_a, product=self.p1, quantity=2)
        OrderItem.objects.create(order=self.order_a, product=self.p2, quantity=1)

        self.order_b = Order.objects.create(
            customer=self.user, status=Order.STATUS_SHIPPED,
        )
        OrderItem.objects.create(order=self.order_b, product=self.p3, quantity=4)

        self.url = f"/api/customers/{self.user.pk}/orders/"

    # --- Shape ---

    def test_returns_expected_shape(self):
        """Each order surfaces its lines with the correct product/warehouse/quantity."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertIn("orders", body)
        orders_by_id = {o["order_id"]: o for o in body["orders"]}
        self.assertEqual(set(orders_by_id), {self.order_a.pk, self.order_b.pk})

        a = orders_by_id[self.order_a.pk]
        self.assertEqual(a["status"], Order.STATUS_PAID)
        self.assertEqual(a["total_cents"], 1500 * 2 + 4200 * 1)
        lines_by_product = {line["product"]: line for line in a["lines"]}
        self.assertEqual(lines_by_product["Widget"]["warehouse"], "Main")
        self.assertEqual(lines_by_product["Widget"]["quantity"], 2)
        self.assertEqual(lines_by_product["Gadget"]["quantity"], 1)

        b = orders_by_id[self.order_b.pk]
        self.assertEqual(b["status"], Order.STATUS_SHIPPED)
        self.assertEqual(b["total_cents"], 999 * 4)
        self.assertEqual(b["lines"][0]["warehouse"], "Backup")

    def test_empty_for_customer_with_no_orders(self):
        """A customer with no orders gets a 200 and an empty list."""
        resp = self.client.get(f"/api/customers/{self.other_user.pk}/orders/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"orders": []})

    # --- 404 ---

    def test_nonexistent_customer_returns_404(self):
        """An unknown customer_id raises Http404.

        Uses RequestFactory to bypass Django's page_not_found template renderer
        (same reason as the other 404 tests in this module).
        """
        request = RequestFactory().get("/api/customers/99999/orders/")
        with self.assertRaises(Http404):
            order_summary(request, customer_id=99999)

    # --- N+1 regression ---

    def test_query_count_is_constant_with_seeded_data(self):
        """The endpoint issues a fixed number of queries with the setUp data."""
        with self.assertNumQueries(self.EXPECTED_QUERIES):
            self.client.get(self.url)

    def test_query_count_does_not_grow_with_orders_and_items(self):
        """Adding more orders and items must not increase the query count.

        Direct regression guard for the N+1 fix: prefetch_related + select_related
        means cost stays at EXPECTED_QUERIES regardless of how many rows match.
        """
        for _ in range(5):
            extra = Order.objects.create(
                customer=self.user, status=Order.STATUS_PAID,
            )
            OrderItem.objects.create(order=extra, product=self.p1, quantity=3)
            OrderItem.objects.create(order=extra, product=self.p2, quantity=2)
            OrderItem.objects.create(order=extra, product=self.p3, quantity=1)

        with self.assertNumQueries(self.EXPECTED_QUERIES):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["orders"]), 2 + 5)
