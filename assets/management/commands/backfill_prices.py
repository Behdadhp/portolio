"""
Pull historical daily prices from Finnhub (stocks) and CoinGecko (crypto)
into the PriceSnapshot table.

Usage:
    python manage.py backfill_prices --days=365
    python manage.py backfill_prices --symbol=BTC --days=90
    python manage.py backfill_prices --kind=crypto --days=180

ETFs are skipped (no API source); their snapshots are populated by the
hourly catchup task from `last_price`.
"""

from django.core.management.base import BaseCommand

from assets.models import Instrument
from assets.services import (
    backfill_coingecko_crypto,
    backfill_finnhub_stock_candles,
)


class Command(BaseCommand):
    help = "Backfill PriceSnapshot rows from Finnhub (stocks) / CoinGecko (crypto)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="How far back to fetch (default 365).",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default=None,
            help="Only backfill this symbol.",
        )
        parser.add_argument(
            "--kind",
            type=str,
            choices=["stock", "crypto"],
            default=None,
            help="Only backfill this kind.",
        )

    def handle(self, *args, **opts):
        days = opts["days"]
        qs = Instrument.objects.exclude(kind="etf")
        if opts["symbol"]:
            qs = qs.filter(symbol__iexact=opts["symbol"])
        if opts["kind"]:
            qs = qs.filter(kind=opts["kind"])

        if not qs.exists():
            self.stdout.write(self.style.WARNING("No matching instruments."))
            return

        total = 0
        for inst in qs:
            self.stdout.write(f"… {inst.kind} {inst.symbol}")
            if inst.kind == "stock":
                n = backfill_finnhub_stock_candles(inst, days=days)
            elif inst.kind == "crypto":
                n = backfill_coingecko_crypto(inst, days=days)
            else:
                continue
            total += n
            self.stdout.write(self.style.SUCCESS(f"  wrote {n} snapshot(s)"))

        self.stdout.write(self.style.SUCCESS(f"Done. {total} snapshots written."))
