import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Status(models.TextChoices):
    BOUGHT = "bought", "Bought"
    SOLD = "sold", "Sold"


class Instrument(models.Model):
    """
    A tradeable instrument (stock, crypto, or ETF). The `kind` field is the
    discriminator; uniqueness is per-kind so a stock symbol may coexist with
    a crypto symbol.
    """

    class Kind(models.TextChoices):
        STOCK = "stock", "Stock"
        CRYPTO = "crypto", "Crypto"
        ETF = "etf", "ETF"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=20)
    finnhub_symbol = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Finnhub symbol (e.g. AAPL, BINANCE:BTCUSDT). Leave blank for "
            "ETFs or any instrument without a live feed."
        ),
    )
    last_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "User-maintained last known price (USD). Primarily used for ETFs "
            "where there is no live feed; mirrored into the price cache."
        ),
    )
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "symbol"], name="instrument_unique_kind_symbol"
            ),
            models.UniqueConstraint(
                fields=["kind", "name"], name="instrument_unique_kind_name"
            ),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # ETFs have no Finnhub feed, so mirror last_price into the shared
        # price cache. Stocks/crypto get their cache from the Finnhub WS.
        if self.kind == self.Kind.ETF:
            if self.last_price is not None:
                cache.set(
                    f"finnhub_{self.symbol}", float(self.last_price), timeout=None
                )
            else:
                cache.delete(f"finnhub_{self.symbol}")

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="transactions"
    )
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.DecimalField(max_digits=24, decimal_places=8)
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.BOUGHT
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.status} {self.amount} ({self.user.email})"


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
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="etf_savings_plans",
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="savings_plans"
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

    def clean(self):
        # Savings plans only make sense for ETFs (no live feed → manual price).
        if self.instrument_id and self.instrument.kind != Instrument.Kind.ETF:
            raise ValidationError(
                {"instrument": "Savings plans can only target ETF instruments."}
            )

    def __str__(self):
        sign = "€" if self.currency == "EUR" else "$"
        return f"{self.instrument.symbol} {sign}{self.amount} {self.interval} ({self.user.email})"


class WatchlistEntry(models.Model):
    """Per-user watchlist — track instruments without holding them."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watchlist"
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="watchers"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "instrument"], name="watchlist_unique_user_instrument"
            ),
        ]

    def __str__(self):
        return f"{self.user.email} watches {self.instrument.symbol}"


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
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="alerts"
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
        return self.instrument.symbol

    @property
    def asset_name(self):
        return self.instrument.name

    def __str__(self):
        direction = "above" if self.direction == "above" else "below"
        return f"{self.symbol} {direction} ${self.target_price} ({self.user.email})"
