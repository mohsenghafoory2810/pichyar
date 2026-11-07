import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase

from catalog import stock
from catalog.models import Category, Product
from catalog.tests.utils import make_product
from orders.models import InvalidTransition, Order, OrderStatus
from payments.services import submit_card_transfer

from .utils import capture_sms, configure_payments, make_order


class OrderLifecycleTests(TestCase):
    def setUp(self):
        configure_payments()
        self.a = make_product("الف", price=100_000, stock=5)
        self.b = make_product("ب", price=200_000, stock=2)
        self.order = make_order((self.a, 3), (self.b, 2))

    def stocks(self):
        return [Product.objects.get(pk=p.pk).stock for p in (self.a, self.b)]

    def submit_card(self):
        submit_card_transfer(self.order, "123456")
        self.order.refresh_from_db()

    def test_card_transfer_waits_for_approval(self):
        self.submit_card()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_APPROVAL)
        self.assertEqual(self.stocks(), [5, 2])
        payment = self.order.payments.get()
        self.assertEqual((payment.tracking_number, payment.amount, payment.status), ("123456", self.order.total, "pending"))

    def test_approve_reserves_stock_once_and_notifies(self):
        self.submit_card()
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(self.order.approve())
            self.assertFalse(self.order.approve())  # idempotent
        self.assertEqual(self.order.status, OrderStatus.PAID_PROCESSING)
        self.assertTrue(self.order.stock_reserved)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(self.stocks(), [2, 0])
        self.assertEqual([k for _, k, _ in sent], ["payment_confirmed"])
        self.assertEqual(self.order.payments.get().status, "succeeded")
        self.assertEqual(self.order.status_logs.filter(to_status=OrderStatus.PAID_PROCESSING).count(), 1)

    def test_approve_without_stock_changes_nothing(self):
        self.submit_card()
        Product.objects.filter(pk=self.b.pk).update(stock=1)
        with self.assertRaises(stock.InsufficientStock):
            self.order.approve()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_APPROVAL)
        self.assertFalse(self.order.stock_reserved)
        self.assertEqual(self.stocks(), [5, 1])

    def test_approve_requires_awaiting_approval(self):
        with self.assertRaises(InvalidTransition):
            self.order.approve()

    def test_reject_cancels(self):
        self.submit_card()
        self.order.reject(reason="رسید نامعتبر")
        self.assertEqual(self.order.status, OrderStatus.CANCELED)
        self.assertEqual(self.order.payments.get().status, "rejected")
        self.assertEqual(self.stocks(), [5, 2])
        with self.assertRaises(InvalidTransition):
            self.order.reject()

    def test_cancel_confirmed_order_restores_stock(self):
        self.submit_card()
        self.order.approve()
        self.order.cancel(note="درخواست مشتری")
        self.assertEqual(self.order.status, OrderStatus.CANCELED)
        self.assertFalse(self.order.stock_reserved)
        self.assertEqual(self.stocks(), [5, 2])

    def test_cancel_unconfirmed_order_leaves_stock(self):
        self.order.cancel()
        self.assertEqual(self.stocks(), [5, 2])

    def test_shipped_orders_cannot_be_canceled(self):
        self.submit_card()
        self.order.approve()
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            self.order.mark_shipped(" 123456789012345678901234 ")
        self.assertEqual(self.order.post_tracking_code, "123456789012345678901234")
        self.assertEqual(sent[0][1], "shipped")
        self.assertEqual(sent[0][2]["tracking_code"], "123456789012345678901234")
        with self.assertRaises(InvalidTransition):
            self.order.cancel()
        self.assertEqual(self.stocks(), [2, 0])
        self.order.mark_delivered()
        self.assertEqual(self.order.status, OrderStatus.DELIVERED)

    def test_status_log_records_every_change(self):
        self.submit_card()
        self.order.approve()
        self.assertEqual(
            list(self.order.status_logs.values_list("from_status", "to_status")),
            [("", "pending_payment"), ("pending_payment", "awaiting_approval"), ("awaiting_approval", "paid_processing")],
        )

    def test_sms_not_sent_when_transaction_rolls_back(self):
        self.submit_card()
        Product.objects.filter(pk=self.b.pk).update(stock=0)
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(stock.InsufficientStock):
                self.order.approve()
        self.assertEqual(sent, [])


class ConcurrentApprovalTests(TransactionTestCase):
    """Two orders compete for the last unit; parallel approvals of one order reserve once."""

    def setUp(self):
        category = Category.objects.create(name="آزمایشی", slug="test-cat")
        self.product = Product.objects.create(name="آخرین", price=1000, stock=1, category=category)
        configure_payments()

    def awaiting_order(self):
        order = make_order((self.product, 1))
        submit_card_transfer(order, "999999")
        return order

    def run_parallel(self, funcs):
        barrier = threading.Barrier(len(funcs))
        results = []
        lock = threading.Lock()

        def worker(func):
            try:
                barrier.wait()
                outcome = "ok" if func() is not False else "noop"
            except stock.InsufficientStock:
                outcome = "short"
            except Exception as e:
                outcome = repr(e)
            finally:
                connection.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker, args=(f,)) for f in funcs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_no_overselling_between_orders(self):
        orders = [self.awaiting_order() for _ in range(4)]
        results = self.run_parallel([lambda o=o: Order.objects.get(pk=o.pk).approve() for o in orders])
        self.assertEqual(sorted(results), ["ok", "short", "short", "short"], results)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(Order.objects.filter(status=OrderStatus.PAID_PROCESSING).count(), 1)

    def test_parallel_approvals_of_one_order_reserve_once(self):
        Product.objects.filter(pk=self.product.pk).update(stock=5)
        order = self.awaiting_order()
        results = self.run_parallel([lambda: Order.objects.get(pk=order.pk).approve() for _ in range(5)])
        self.assertEqual(sorted(results), ["noop"] * 4 + ["ok"], results)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
