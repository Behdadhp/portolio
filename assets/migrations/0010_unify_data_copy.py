"""
Data migration: copy legacy Stock/Crypto/ETF rows into Instrument, and
StockAsset/CryptoAsset/ETFAsset rows into Transaction. Backfill the new
`instrument` FK on PriceAlert and ETFSavingsPlan from their legacy FKs.

Old IDs are preserved as new IDs (UUIDs are globally unique, so no
collisions are possible across tables). This makes downstream code that
references the old PKs continue to work transparently.
"""

from decimal import Decimal

from django.db import migrations


def copy_to_instrument_and_transaction(apps, schema_editor):
    Stock = apps.get_model("assets", "Stock")
    Crypto = apps.get_model("assets", "Crypto")
    ETF = apps.get_model("assets", "ETF")
    StockAsset = apps.get_model("assets", "StockAsset")
    CryptoAsset = apps.get_model("assets", "CryptoAsset")
    ETFAsset = apps.get_model("assets", "ETFAsset")
    PriceAlert = apps.get_model("assets", "PriceAlert")
    ETFSavingsPlan = apps.get_model("assets", "ETFSavingsPlan")
    Instrument = apps.get_model("assets", "Instrument")
    Transaction = apps.get_model("assets", "Transaction")

    # 1. Instruments (preserve IDs).
    for s in Stock.objects.all():
        Instrument.objects.create(
            id=s.id,
            kind="stock",
            name=s.name,
            symbol=s.symbol,
            finnhub_symbol=s.finnhub_symbol or "",
            last_price=None,
            date_added=s.date_added,
        )
    for c in Crypto.objects.all():
        Instrument.objects.create(
            id=c.id,
            kind="crypto",
            name=c.name,
            symbol=c.symbol,
            finnhub_symbol=c.finnhub_symbol or "",
            last_price=None,
            date_added=c.date_added,
        )
    for e in ETF.objects.all():
        Instrument.objects.create(
            id=e.id,
            kind="etf",
            name=e.name,
            symbol=e.symbol,
            finnhub_symbol="",
            last_price=e.last_price,
            date_added=e.date_added,
        )

    # 2. Transactions (preserve IDs; convert float amount to Decimal).
    def _amount(f):
        # Normalise float → Decimal via str() to avoid binary-float artefacts.
        return Decimal(str(f or 0)).quantize(Decimal("0.00000001"))

    for t in StockAsset.objects.all():
        Transaction.objects.create(
            id=t.id,
            user_id=t.user_id,
            instrument_id=t.stock_id,
            price=t.price,
            amount=_amount(t.amount),
            date=t.date,
            status=t.status,
        )
    for t in CryptoAsset.objects.all():
        Transaction.objects.create(
            id=t.id,
            user_id=t.user_id,
            instrument_id=t.crypto_id,
            price=t.price,
            amount=_amount(t.amount),
            date=t.date,
            status=t.status,
        )
    for t in ETFAsset.objects.all():
        Transaction.objects.create(
            id=t.id,
            user_id=t.user_id,
            instrument_id=t.etf_id,
            price=t.price,
            amount=_amount(t.amount),
            date=t.date,
            status=t.status,
        )

    # 3. PriceAlert backfill — instrument is whichever legacy FK is set.
    for a in PriceAlert.objects.all():
        target_id = a.stock_id or a.crypto_id or a.etf_id
        if target_id is None:
            # Orphan — leave instrument null; will be cleaned up in step 4.
            continue
        a.instrument_id = target_id
        a.save(update_fields=["instrument"])

    # 4. ETFSavingsPlan backfill.
    for p in ETFSavingsPlan.objects.all():
        if p.etf_id is None:
            continue
        p.instrument_id = p.etf_id
        p.save(update_fields=["instrument"])


def reverse(apps, schema_editor):
    """No-op reverse: rely on the pre-unify DB backup if you need to roll back."""
    Instrument = apps.get_model("assets", "Instrument")
    Transaction = apps.get_model("assets", "Transaction")
    PriceAlert = apps.get_model("assets", "PriceAlert")
    ETFSavingsPlan = apps.get_model("assets", "ETFSavingsPlan")

    PriceAlert.objects.update(instrument=None)
    ETFSavingsPlan.objects.update(instrument=None)
    Transaction.objects.all().delete()
    Instrument.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0009_unify_instrument_transaction_add"),
    ]

    operations = [
        migrations.RunPython(copy_to_instrument_and_transaction, reverse),
    ]
