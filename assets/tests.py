from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from .forms import CryptoAssetForm, StockAssetForm
from .models import Instrument, Transaction


def _stock(name="Apple", symbol="AAPL"):
    return Instrument.objects.create(kind=Instrument.Kind.STOCK, name=name, symbol=symbol)


def _crypto(name="Bitcoin", symbol="BTC"):
    return Instrument.objects.create(kind=Instrument.Kind.CRYPTO, name=name, symbol=symbol)


class TestDataMixin:
    """Creates a user, a stock instrument, a crypto instrument."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="Test1234",
            first_name="Other",
            last_name="User",
            birthdate="1991-01-01",
        )
        self.stock = _stock()
        self.crypto = _crypto()
        self.client.login(username="test@example.com", password="Test1234")


# ── Model tests ──────────────────────────────────────────────


class InstrumentModelTest(TestCase):
    def test_str(self):
        crypto = _crypto()
        self.assertEqual(str(crypto), "Bitcoin (BTC)")

    def test_uuid_pk(self):
        crypto = _crypto(name="Ethereum", symbol="ETH")
        self.assertEqual(str(crypto.pk).count("-"), 4)

    def test_unique_kind_symbol(self):
        _crypto()
        with self.assertRaises(Exception):
            _crypto(name="Bitcoin2")  # same symbol, same kind

    def test_unique_kind_name(self):
        _crypto()
        with self.assertRaises(Exception):
            _crypto(symbol="BTC2")  # same name, same kind

    def test_same_symbol_across_kinds_allowed(self):
        Instrument.objects.create(kind="stock", name="Foo", symbol="X")
        # Different kind, same symbol — must succeed.
        Instrument.objects.create(kind="crypto", name="FooCoin", symbol="X")


class TransactionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )
        self.crypto = _crypto()

    def test_create_transaction(self):
        tx = Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("50000.00"),
            amount=Decimal("1.5"),
            date=date(2024, 1, 15),
            status="bought",
        )
        self.assertIn("BTC", str(tx))

    def test_default_status_is_bought(self):
        tx = Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("100.00"),
            amount=Decimal("1.0"),
            date=date(2024, 1, 1),
        )
        self.assertEqual(tx.status, "bought")

    def test_cascade_delete_user(self):
        Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("100.00"),
            amount=Decimal("1.0"),
            date=date(2024, 1, 1),
        )
        self.user.delete()
        self.assertEqual(Transaction.objects.count(), 0)

    def test_cascade_delete_instrument(self):
        Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("100.00"),
            amount=Decimal("1.0"),
            date=date(2024, 1, 1),
        )
        self.crypto.delete()
        self.assertEqual(Transaction.objects.count(), 0)


# ── Form tests ───────────────────────────────────────────────


class StockAssetFormTest(TestCase):
    def setUp(self):
        self.stock = _stock()

    def test_valid_form(self):
        form = StockAssetForm(
            data={
                "stock": self.stock.pk,
                "price": "150.00",
                "amount": "10.0",
                "date": "2024-03-01",
                "status": "bought",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_stock(self):
        form = StockAssetForm(
            data={
                "price": "150.00",
                "amount": "10.0",
                "date": "2024-03-01",
                "status": "bought",
            }
        )
        self.assertFalse(form.is_valid())

    def test_missing_date(self):
        form = StockAssetForm(
            data={
                "stock": self.stock.pk,
                "price": "150.00",
                "amount": "10.0",
                "status": "bought",
            }
        )
        self.assertFalse(form.is_valid())

    def test_only_stocks_in_dropdown(self):
        # A crypto should not be selectable in StockAssetForm.
        crypto = _crypto()
        form = StockAssetForm(
            data={
                "stock": crypto.pk,
                "price": "1.00",
                "amount": "1.0",
                "date": "2024-03-01",
                "status": "bought",
            }
        )
        self.assertFalse(form.is_valid())


class CryptoAssetFormTest(TestCase):
    def setUp(self):
        self.crypto = _crypto()

    def test_valid_form(self):
        form = CryptoAssetForm(
            data={
                "crypto": self.crypto.pk,
                "price": "50000.00",
                "amount": "0.5",
                "date": "2024-01-15",
                "status": "bought",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_status(self):
        form = CryptoAssetForm(
            data={
                "crypto": self.crypto.pk,
                "price": "50000.00",
                "amount": "0.5",
                "date": "2024-01-15",
                "status": "invalid",
            }
        )
        self.assertFalse(form.is_valid())


# ── Stock view tests ─────────────────────────────────────────


class StockListViewTest(TestDataMixin, TestCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("stocks"))
        self.assertEqual(response.status_code, 302)

    def test_empty_list(self):
        response = self.client.get(reverse("stocks"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No stock assets yet")

    def test_shows_unique_stocks_with_totals(self):
        Transaction.objects.create(
            user=self.user,
            instrument=self.stock,
            price=Decimal("100.00"),
            amount=Decimal("10.0"),
            date=date(2024, 1, 1),
            status="bought",
        )
        Transaction.objects.create(
            user=self.user,
            instrument=self.stock,
            price=Decimal("110.00"),
            amount=Decimal("3.0"),
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.get(reverse("stocks"))
        self.assertContains(response, "AAPL")
        self.assertContains(response, "7.00")  # 10 - 3 = 7

    def test_does_not_show_other_users_assets(self):
        Transaction.objects.create(
            user=self.other_user,
            instrument=self.stock,
            price=Decimal("100.00"),
            amount=Decimal("5.0"),
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.get(reverse("stocks"))
        self.assertContains(response, "No stock assets yet")


class StockDetailViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx1 = Transaction.objects.create(
            user=self.user,
            instrument=self.stock,
            price=Decimal("150.00"),
            amount=Decimal("10.0"),
            date=date(2024, 1, 15),
            status="bought",
        )
        self.tx2 = Transaction.objects.create(
            user=self.user,
            instrument=self.stock,
            price=Decimal("160.00"),
            amount=Decimal("5.0"),
            date=date(2024, 3, 1),
            status="sold",
        )

    def test_renders(self):
        response = self.client.get(reverse("stock_detail", args=["AAPL"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple")

    def test_invalid_symbol_returns_404(self):
        response = self.client.get(reverse("stock_detail", args=["FAKE"]))
        self.assertEqual(response.status_code, 404)

    def test_filter_by_status_bought(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?status=bought"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)
        self.assertEqual(page_obj[0].status, "bought")

    def test_invalid_per_page_defaults(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?per_page=999"
        )
        self.assertEqual(response.context["per_page"], 20)


class StockAddViewTest(TestDataMixin, TestCase):
    def test_add_page_renders(self):
        response = self.client.get(reverse("stock_add"))
        self.assertEqual(response.status_code, 200)

    def test_add_transaction(self):
        response = self.client.post(
            reverse("stock_add"),
            {
                "stock": self.stock.pk,
                "price": "150.00",
                "amount": "10.0",
                "date": "2024-03-01",
                "status": "bought",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Transaction.objects.filter(
                user=self.user, instrument__kind="stock"
            ).count(),
            1,
        )

    def test_add_assigns_current_user(self):
        self.client.post(
            reverse("stock_add"),
            {
                "stock": self.stock.pk,
                "price": "150.00",
                "amount": "10.0",
                "date": "2024-03-01",
                "status": "bought",
            },
        )
        tx = Transaction.objects.filter(instrument__kind="stock").first()
        self.assertEqual(tx.user, self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("stock_add"))
        self.assertEqual(response.status_code, 302)


class StockDeleteViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx = Transaction.objects.create(
            user=self.user,
            instrument=self.stock,
            price=Decimal("150.00"),
            amount=Decimal("10.0"),
            date=date(2024, 1, 15),
            status="bought",
        )

    def test_delete_transaction(self):
        response = self.client.post(reverse("stock_delete", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Transaction.objects.filter(pk=self.tx.pk).exists())

    def test_cannot_delete_other_users_transaction(self):
        other_tx = Transaction.objects.create(
            user=self.other_user,
            instrument=self.stock,
            price=Decimal("100.00"),
            amount=Decimal("5.0"),
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.post(reverse("stock_delete", args=[other_tx.pk]))
        self.assertEqual(response.status_code, 404)


# ── Crypto view tests ────────────────────────────────────────


class CryptoListViewTest(TestDataMixin, TestCase):
    def test_empty_list(self):
        response = self.client.get(reverse("crypto"))
        self.assertContains(response, "No crypto assets yet")

    def test_shows_unique_cryptos_with_totals(self):
        Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("50000.00"),
            amount=Decimal("2.0"),
            date=date(2024, 1, 1),
            status="bought",
        )
        Transaction.objects.create(
            user=self.user,
            instrument=self.crypto,
            price=Decimal("55000.00"),
            amount=Decimal("0.5"),
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.get(reverse("crypto"))
        self.assertContains(response, "BTC")
        self.assertContains(response, "1.50")  # 2.0 - 0.5


class CryptoDetailViewTest(TestDataMixin, TestCase):
    def test_invalid_symbol_returns_404(self):
        response = self.client.get(reverse("crypto_detail", args=["FAKE"]))
        self.assertEqual(response.status_code, 404)
