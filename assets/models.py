import uuid
from django.conf import settings
from django.db import models


class Crypto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name_plural = "Cryptos"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class Stock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, unique=True)

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
    crypto = models.ForeignKey(Crypto, on_delete=models.CASCADE, related_name="transactions")
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.FloatField(default=0.0)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOUGHT)

    def __str__(self):
        return f"{self.crypto.name} - {self.user.email}"


class StockAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stock_assets"
    )
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name="transactions")
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.FloatField(default=0.0)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOUGHT)

    def __str__(self):
        return f"{self.stock.name} - {self.user.email}"
