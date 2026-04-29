import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Crypto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, unique=True)
    finnhub_symbol = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Finnhub symbol (e.g. BINANCE:BTCUSDT). Leave blank to skip live tracking.",
    )
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Cryptos"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class Stock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, unique=True)
    finnhub_symbol = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Finnhub symbol (e.g. AAPL). Leave blank to skip live tracking.",
    )
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class ETF(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, unique=True)
    last_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="User-maintained last known price (USD). Used for analytics and savings-plan auto-transactions.",
    )
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "ETF"
        verbose_name_plural = "ETFs"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Mirror last_price into the shared price cache so analytics/list views
        # transparently use it (same key shape as Finnhub-tracked assets).
        from django.core.cache import cache
        if self.last_price is not None:
            cache.set(f"finnhub_{self.symbol}", float(self.last_price), timeout=None)
        else:
            cache.delete(f"finnhub_{self.symbol}")

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class Status(models.TextChoices):
    BOUGHT = "bought", "Bought"
    SOLD = "sold", "Sold"


class CryptoAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crypto_assets"
    )
    crypto = models.ForeignKey(
        Crypto, on_delete=models.CASCADE, related_name="transactions"
    )
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.FloatField(default=0.0)
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.BOUGHT
    )

    def __str__(self):
        return f"{self.crypto.name} - {self.user.email}"


class StockAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stock_assets"
    )
    stock = models.ForeignKey(
        Stock, on_delete=models.CASCADE, related_name="transactions"
    )
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.FloatField(default=0.0)
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.BOUGHT
    )

    def __str__(self):
        return f"{self.stock.name} - {self.user.email}"


class ETFAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="etf_assets"
    )
    etf = models.ForeignKey(
        ETF, on_delete=models.CASCADE, related_name="transactions"
    )
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.FloatField(default=0.0)
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.BOUGHT
    )

    def __str__(self):
        return f"{self.etf.name} - {self.user.email}"


class ETFSavingsPlan(models.Model):
    class Interval(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        BIWEEKLY = "biweekly", "Bi-weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"

    class Currency(models.TextChoices):
        USD = "USD", "USD"
        EUR = "EUR", "EUR"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="etf_savings_plans"
    )
    etf = models.ForeignKey(
        ETF, on_delete=models.CASCADE, related_name="savings_plans"
    )
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Amount to invest each interval, in the plan's currency.",
    )
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.USD,
        help_text="Currency of `amount`. EUR plans are converted to USD at execution time.",
    )
    interval = models.CharField(
        max_length=10, choices=Interval.choices, default=Interval.MONTHLY
    )
    start_date = models.DateField(
        help_text="Original start date (used to anchor day-of-month). Never changes."
    )
    next_execution_date = models.DateField(
        help_text="Next date the plan will auto-execute. Advances after each run."
    )
    last_executed_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        sign = "€" if self.currency == "EUR" else "$"
        return f"{self.etf.symbol} {sign}{self.amount} {self.interval} ({self.user.email})"


class CashFlow(models.Model):
    """
    External money moving in or out of the brokerage account.
    Always stored in USD (EUR inputs are converted at submit time).
    """

    class Direction(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAW = "withdraw", "Withdraw"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cash_flows"
    )
    amount_usd = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Amount in USD. EUR inputs are converted on save.",
    )
    direction = models.CharField(
        max_length=10, choices=Direction.choices, default=Direction.DEPOSIT
    )
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        sign = "+" if self.direction == "deposit" else "-"
        return f"{sign}${self.amount_usd} {self.date} ({self.user.email})"


class PriceAlert(models.Model):
    class Direction(models.TextChoices):
        ABOVE = "above", "Above (Sell)"
        BELOW = "below", "Below (Buy)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="price_alerts"
    )
    stock = models.ForeignKey(
        Stock, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    crypto = models.ForeignKey(
        Crypto, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    etf = models.ForeignKey(
        ETF, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    target_price = models.DecimalField(max_digits=18, decimal_places=2)
    direction = models.CharField(
        max_length=5, choices=Direction.choices, default=Direction.ABOVE
    )
    invest_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "USD amount the user plans to spend when a 'below' (buy) alert "
            "triggers. Null for sell alerts."
        ),
    )
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def symbol(self):
        if self.stock_id:
            return self.stock.symbol
        if self.etf_id:
            return self.etf.symbol
        return self.crypto.symbol

    @property
    def asset_name(self):
        if self.stock_id:
            return self.stock.name
        if self.etf_id:
            return self.etf.name
        return self.crypto.name

    def __str__(self):
        direction = "above" if self.direction == "above" else "below"
        return f"{self.symbol} {direction} ${self.target_price} ({self.user.email})"
