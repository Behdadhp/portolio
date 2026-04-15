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
    target_price = models.DecimalField(max_digits=18, decimal_places=2)
    direction = models.CharField(
        max_length=5, choices=Direction.choices, default=Direction.ABOVE
    )
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def symbol(self):
        if self.stock_id:
            return self.stock.symbol
        return self.crypto.symbol

    @property
    def asset_name(self):
        if self.stock_id:
            return self.stock.name
        return self.crypto.name

    def __str__(self):
        direction = "above" if self.direction == "above" else "below"
        return f"{self.symbol} {direction} ${self.target_price} ({self.user.email})"
