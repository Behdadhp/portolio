from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from .forms import CryptoAssetForm, StockAssetForm
from .models import Crypto, CryptoAsset, Stock, StockAsset


class TestDataMixin:
    """Creates a user, a stock, a crypto, and some transactions for tests."""

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
        self.stock = Stock.objects.create(name="Apple", symbol="AAPL")
        self.crypto = Crypto.objects.create(name="Bitcoin", symbol="BTC")
        self.client.login(username="test@example.com", password="Test1234")


# ── Model tests ──────────────────────────────────────────────


class CryptoModelTest(TestCase):
    def test_str(self):
        crypto = Crypto.objects.create(name="Bitcoin", symbol="BTC")
        self.assertEqual(str(crypto), "Bitcoin (BTC)")

    def test_uuid_pk(self):
        crypto = Crypto.objects.create(name="Ethereum", symbol="ETH")
        self.assertEqual(str(crypto.pk).count("-"), 4)

    def test_unique_name(self):
        Crypto.objects.create(name="Bitcoin", symbol="BTC")
        with self.assertRaises(Exception):
            Crypto.objects.create(name="Bitcoin", symbol="BTC2")

    def test_unique_symbol(self):
        Crypto.objects.create(name="Bitcoin", symbol="BTC")
        with self.assertRaises(Exception):
            Crypto.objects.create(name="Bitcoin2", symbol="BTC")


class StockModelTest(TestCase):
    def test_str(self):
        stock = Stock.objects.create(name="Apple", symbol="AAPL")
        self.assertEqual(str(stock), "Apple (AAPL)")

    def test_uuid_pk(self):
        stock = Stock.objects.create(name="Apple", symbol="AAPL")
        self.assertEqual(str(stock.pk).count("-"), 4)


class CryptoAssetModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )
        self.crypto = Crypto.objects.create(name="Bitcoin", symbol="BTC")

    def test_create_crypto_asset(self):
        asset = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.5,
            date=date(2024, 1, 15),
            status="bought",
        )
        self.assertEqual(str(asset), "Bitcoin - test@example.com")

    def test_default_status_is_bought(self):
        asset = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("100.00"),
            amount=1.0,
            date=date(2024, 1, 1),
        )
        self.assertEqual(asset.status, "bought")

    def test_cascade_delete_user(self):
        CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("100.00"),
            amount=1.0,
            date=date(2024, 1, 1),
        )
        self.user.delete()
        self.assertEqual(CryptoAsset.objects.count(), 0)

    def test_cascade_delete_crypto(self):
        CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("100.00"),
            amount=1.0,
            date=date(2024, 1, 1),
        )
        self.crypto.delete()
        self.assertEqual(CryptoAsset.objects.count(), 0)


class StockAssetModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )
        self.stock = Stock.objects.create(name="Apple", symbol="AAPL")

    def test_create_stock_asset(self):
        asset = StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("150.00"),
            amount=10.0,
            date=date(2024, 3, 1),
            status="bought",
        )
        self.assertEqual(str(asset), "Apple - test@example.com")


# ── Form tests ───────────────────────────────────────────────


class StockAssetFormTest(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(name="Apple", symbol="AAPL")

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
        self.assertTrue(form.is_valid())

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


class CryptoAssetFormTest(TestCase):
    def setUp(self):
        self.crypto = Crypto.objects.create(name="Bitcoin", symbol="BTC")

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
        self.assertTrue(form.is_valid())

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
        self.assertContains(response, "You have no stock assets yet.")

    def test_shows_unique_stocks_with_totals(self):
        StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("100.00"),
            amount=10.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("110.00"),
            amount=3.0,
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.get(reverse("stocks"))
        self.assertContains(response, "AAPL")
        self.assertContains(response, "7.00")  # 10 - 3 = 7

    def test_does_not_show_other_users_assets(self):
        StockAsset.objects.create(
            user=self.other_user,
            stock=self.stock,
            price=Decimal("100.00"),
            amount=5.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.get(reverse("stocks"))
        self.assertContains(response, "You have no stock assets yet.")


class StockDetailViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx1 = StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("150.00"),
            amount=10.0,
            date=date(2024, 1, 15),
            status="bought",
        )
        self.tx2 = StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("160.00"),
            amount=5.0,
            date=date(2024, 3, 1),
            status="sold",
        )

    def test_renders(self):
        response = self.client.get(reverse("stock_detail", args=["AAPL"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple")

    def test_shows_total_amount(self):
        response = self.client.get(reverse("stock_detail", args=["AAPL"]))
        self.assertContains(response, "5.00")  # 10 - 5

    def test_invalid_symbol_returns_404(self):
        response = self.client.get(reverse("stock_detail", args=["FAKE"]))
        self.assertEqual(response.status_code, 404)

    def test_sorting_by_price_asc(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?sort=price&order=asc"
        )
        self.assertEqual(response.status_code, 200)

    def test_sorting_by_date_desc(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?sort=date&order=desc"
        )
        self.assertEqual(response.status_code, 200)

    def test_pagination_per_page(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?per_page=20"
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_per_page_defaults(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?per_page=999"
        )
        self.assertEqual(response.context["per_page"], 20)

    def test_filter_by_status_bought(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?status=bought"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)
        self.assertEqual(page_obj[0].status, "bought")

    def test_filter_by_status_sold(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?status=sold"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)
        self.assertEqual(page_obj[0].status, "sold")

    def test_filter_by_date_range(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"])
            + "?date_from=2024-02-01&date_to=2024-12-31"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)

    def test_filter_by_price_range(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?price_min=155&price_max=200"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)

    def test_filter_by_amount_range(self):
        response = self.client.get(
            reverse("stock_detail", args=["AAPL"]) + "?amount_min=8&amount_max=12"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)


class StockAddViewTest(TestDataMixin, TestCase):
    def test_add_page_renders(self):
        response = self.client.get(reverse("stock_add"))
        self.assertEqual(response.status_code, 200)

    def test_add_with_preselected_stock(self):
        response = self.client.get(reverse("stock_add_for", args=["AAPL"]))
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
        self.assertEqual(StockAsset.objects.filter(user=self.user).count(), 1)

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
        asset = StockAsset.objects.first()
        self.assertEqual(asset.user, self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("stock_add"))
        self.assertEqual(response.status_code, 302)


class StockEditViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx = StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("150.00"),
            amount=10.0,
            date=date(2024, 1, 15),
            status="bought",
        )

    def test_edit_page_renders(self):
        response = self.client.get(reverse("stock_edit", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_transaction(self):
        response = self.client.post(
            reverse("stock_edit", args=[self.tx.pk]),
            {
                "stock": self.stock.pk,
                "price": "200.00",
                "amount": "15.0",
                "date": "2024-02-01",
                "status": "sold",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.price, Decimal("200.00"))
        self.assertEqual(self.tx.amount, 15.0)
        self.assertEqual(self.tx.status, "sold")

    def test_cannot_edit_other_users_transaction(self):
        other_tx = StockAsset.objects.create(
            user=self.other_user,
            stock=self.stock,
            price=Decimal("100.00"),
            amount=5.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.get(reverse("stock_edit", args=[other_tx.pk]))
        self.assertEqual(response.status_code, 404)


class StockDeleteViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx = StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("150.00"),
            amount=10.0,
            date=date(2024, 1, 15),
            status="bought",
        )

    def test_delete_confirmation_page_renders(self):
        response = self.client.get(reverse("stock_delete", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Are you sure?")

    def test_delete_transaction(self):
        response = self.client.post(reverse("stock_delete", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(StockAsset.objects.filter(pk=self.tx.pk).exists())

    def test_delete_last_transaction_redirects_to_list(self):
        response = self.client.post(reverse("stock_delete", args=[self.tx.pk]))
        self.assertRedirects(response, reverse("stocks"))

    def test_delete_keeps_remaining_redirects_to_detail(self):
        StockAsset.objects.create(
            user=self.user,
            stock=self.stock,
            price=Decimal("200.00"),
            amount=5.0,
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.post(reverse("stock_delete", args=[self.tx.pk]))
        self.assertRedirects(response, reverse("stock_detail", args=["AAPL"]))

    def test_cannot_delete_other_users_transaction(self):
        other_tx = StockAsset.objects.create(
            user=self.other_user,
            stock=self.stock,
            price=Decimal("100.00"),
            amount=5.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.post(reverse("stock_delete", args=[other_tx.pk]))
        self.assertEqual(response.status_code, 404)


# ── Crypto view tests ────────────────────────────────────────


class CryptoListViewTest(TestDataMixin, TestCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("crypto"))
        self.assertEqual(response.status_code, 302)

    def test_empty_list(self):
        response = self.client.get(reverse("crypto"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no crypto assets yet.")

    def test_shows_unique_cryptos_with_totals(self):
        CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=2.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("55000.00"),
            amount=0.5,
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.get(reverse("crypto"))
        self.assertContains(response, "BTC")
        self.assertContains(response, "1.50")  # 2.0 - 0.5

    def test_does_not_show_other_users_assets(self):
        CryptoAsset.objects.create(
            user=self.other_user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.get(reverse("crypto"))
        self.assertContains(response, "You have no crypto assets yet.")


class CryptoDetailViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx1 = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=2.0,
            date=date(2024, 1, 15),
            status="bought",
        )
        self.tx2 = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("55000.00"),
            amount=0.5,
            date=date(2024, 3, 1),
            status="sold",
        )

    def test_renders(self):
        response = self.client.get(reverse("crypto_detail", args=["BTC"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bitcoin")

    def test_shows_total_amount(self):
        response = self.client.get(reverse("crypto_detail", args=["BTC"]))
        self.assertContains(response, "1.50")  # 2.0 - 0.5

    def test_invalid_symbol_returns_404(self):
        response = self.client.get(reverse("crypto_detail", args=["FAKE"]))
        self.assertEqual(response.status_code, 404)

    def test_filter_by_status(self):
        response = self.client.get(
            reverse("crypto_detail", args=["BTC"]) + "?status=bought"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)

    def test_filter_by_date_range(self):
        response = self.client.get(
            reverse("crypto_detail", args=["BTC"]) + "?date_from=2024-02-01"
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj), 1)

    def test_sorting(self):
        response = self.client.get(
            reverse("crypto_detail", args=["BTC"]) + "?sort=amount&order=asc"
        )
        self.assertEqual(response.status_code, 200)


class CryptoAddViewTest(TestDataMixin, TestCase):
    def test_add_page_renders(self):
        response = self.client.get(reverse("crypto_add"))
        self.assertEqual(response.status_code, 200)

    def test_add_with_preselected_crypto(self):
        response = self.client.get(reverse("crypto_add_for", args=["BTC"]))
        self.assertEqual(response.status_code, 200)

    def test_add_transaction(self):
        response = self.client.post(
            reverse("crypto_add"),
            {
                "crypto": self.crypto.pk,
                "price": "50000.00",
                "amount": "1.5",
                "date": "2024-01-15",
                "status": "bought",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CryptoAsset.objects.filter(user=self.user).count(), 1)

    def test_add_assigns_current_user(self):
        self.client.post(
            reverse("crypto_add"),
            {
                "crypto": self.crypto.pk,
                "price": "50000.00",
                "amount": "1.5",
                "date": "2024-01-15",
                "status": "bought",
            },
        )
        asset = CryptoAsset.objects.first()
        self.assertEqual(asset.user, self.user)


class CryptoEditViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.0,
            date=date(2024, 1, 15),
            status="bought",
        )

    def test_edit_page_renders(self):
        response = self.client.get(reverse("crypto_edit", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_transaction(self):
        response = self.client.post(
            reverse("crypto_edit", args=[self.tx.pk]),
            {
                "crypto": self.crypto.pk,
                "price": "60000.00",
                "amount": "2.0",
                "date": "2024-02-01",
                "status": "sold",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.price, Decimal("60000.00"))
        self.assertEqual(self.tx.status, "sold")

    def test_cannot_edit_other_users_transaction(self):
        other_tx = CryptoAsset.objects.create(
            user=self.other_user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.get(reverse("crypto_edit", args=[other_tx.pk]))
        self.assertEqual(response.status_code, 404)


class CryptoDeleteViewTest(TestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tx = CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.0,
            date=date(2024, 1, 15),
            status="bought",
        )

    def test_delete_confirmation_page_renders(self):
        response = self.client.get(reverse("crypto_delete", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Are you sure?")

    def test_delete_transaction(self):
        response = self.client.post(reverse("crypto_delete", args=[self.tx.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CryptoAsset.objects.filter(pk=self.tx.pk).exists())

    def test_delete_last_transaction_redirects_to_list(self):
        response = self.client.post(reverse("crypto_delete", args=[self.tx.pk]))
        self.assertRedirects(response, reverse("crypto"))

    def test_delete_keeps_remaining_redirects_to_detail(self):
        CryptoAsset.objects.create(
            user=self.user,
            crypto=self.crypto,
            price=Decimal("55000.00"),
            amount=0.5,
            date=date(2024, 2, 1),
            status="sold",
        )
        response = self.client.post(reverse("crypto_delete", args=[self.tx.pk]))
        self.assertRedirects(response, reverse("crypto_detail", args=["BTC"]))

    def test_cannot_delete_other_users_transaction(self):
        other_tx = CryptoAsset.objects.create(
            user=self.other_user,
            crypto=self.crypto,
            price=Decimal("50000.00"),
            amount=1.0,
            date=date(2024, 1, 1),
            status="bought",
        )
        response = self.client.post(reverse("crypto_delete", args=[other_tx.pk]))
        self.assertEqual(response.status_code, 404)
