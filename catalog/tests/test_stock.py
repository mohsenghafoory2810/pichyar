import threading

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from catalog import stock
from catalog.models import Category, Product

from .utils import make_product


class ReserveReleaseTests(TestCase):
    def setUp(self):
        self.a = make_product("الف", stock=5)
        self.b = make_product("ب", stock=2)

    def stocks(self):
        return list(
            Product.objects.filter(pk__in=[self.a.pk, self.b.pk]).order_by("pk").values_list("stock", flat=True)
        )

    def test_reserve_decreases_stock(self):
        stock.reserve({self.a.pk: 3, self.b.pk: 2})
        self.assertEqual(self.stocks(), [2, 0])

    def test_reserve_accepts_product_pairs_and_merges_duplicates(self):
        stock.reserve([(self.a, 2), (self.a, 2)])
        self.assertEqual(self.stocks(), [1, 2])

    def test_insufficient_stock_reserves_nothing(self):
        with self.assertRaises(stock.InsufficientStock) as ctx:
            stock.reserve({self.a.pk: 1, self.b.pk: 3})
        self.assertEqual(self.stocks(), [5, 2])
        self.assertEqual(ctx.exception.shortages, [(self.b, 3, 2)])
        self.assertIn("موجودی «ب» کافی نیست (درخواست: ۳، موجود: ۲)", str(ctx.exception))

    def test_out_of_stock_message(self):
        self.b.stock = 0
        self.b.save()
        with self.assertRaisesMessage(stock.InsufficientStock, "«ب» ناموجود است."):
            stock.reserve({self.b.pk: 1})

    def test_release_returns_stock(self):
        stock.reserve({self.a.pk: 5})
        stock.release({self.a.pk: 5})
        self.assertEqual(self.stocks(), [5, 2])

    def test_invalid_quantity(self):
        for qty in (0, -1):
            with self.assertRaises(ValueError):
                stock.reserve({self.a.pk: qty})
        self.assertEqual(self.stocks(), [5, 2])

    def test_unknown_product(self):
        with self.assertRaises(Product.DoesNotExist):
            stock.reserve({self.a.pk: 1, 999_999: 1})
        self.assertEqual(self.stocks(), [5, 2])

    def test_database_refuses_negative_stock(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=self.a.pk).update(stock=-1)

    def test_can_add_to_cart(self):
        self.assertTrue(stock.can_add_to_cart(self.a, 5))
        self.assertFalse(stock.can_add_to_cart(self.a, 6))
        self.b.stock = 0
        self.assertFalse(stock.can_add_to_cart(self.b))
        self.a.is_active = False
        self.assertFalse(stock.can_add_to_cart(self.a))


class ConcurrentReserveTests(TransactionTestCase):
    """Real parallel connections (the test database is a file, see settings/test.py)."""

    def setUp(self):
        category = Category.objects.create(name="آزمایشی", slug="test-cat")
        self.product = Product.objects.create(name="پرفروش", price=1000, stock=5, category=category)

    def run_parallel(self, n, qty):
        barrier = threading.Barrier(n)
        results = []
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait()
                stock.reserve({self.product.pk: qty})
                outcome = "ok"
            except stock.InsufficientStock:
                outcome = "short"
            except Exception as e:  # reported by the assertions below
                outcome = repr(e)
            finally:
                connection.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_never_oversells(self):
        results = self.run_parallel(12, 1)
        self.assertEqual(results.count("ok"), 5, results)
        self.assertEqual(results.count("short"), 7, results)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)

    def test_only_one_large_order_wins(self):
        results = self.run_parallel(6, 3)
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(results.count("short"), 5, results)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)

    def test_parallel_reserve_and_release_balance_out(self):
        barrier = threading.Barrier(8)

        def worker(i):
            try:
                barrier.wait()
                if i % 2:
                    stock.release({self.product.pk: 1})
                else:
                    stock.reserve({self.product.pk: 1})
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
