"""
Live-price plumbing: cache reads, EUR→USD FX, PriceSnapshot writes,
Finnhub / CoinGecko backfills, master-record sync, and the Finnhub-probe
``lookup_instrument`` used by both the master-record create flow and the
JSON ``/api/lookup-instrument/`` endpoint.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def load_live_prices(kind, watchlist_ids=None):
    """
    Load cached live prices and market caps for tracked symbols of a kind.

    `watchlist_ids` (a set of UUIDs) lets the Market page mark each row as
    already watched.
    """
    from ..models import Instrument

    if watchlist_ids is None:
        watchlist_ids = set()

    result = []
    for inst in Instrument.objects.filter(kind=kind).exclude(finnhub_symbol=""):
        price = cache.get(f"finnhub_{inst.symbol}")
        mcap = cache.get(f"finnhub_{inst.symbol}_mcap")
        result.append({
            "id": str(inst.id),
            "short": inst.symbol,
            "price": price,
            "market_cap": mcap or 0,
            "watching": inst.id in watchlist_ids,
        })
    result.sort(key=lambda x: x["market_cap"], reverse=True)
    return result


def get_eur_usd_rate():
    """
    Get the current EUR → USD exchange rate.

    Caches the rate for 6 hours (ECB updates daily).
    Returns None if the API is unreachable.
    """
    CACHE_KEY = "fx_eur_usd"
    UNAVAILABLE_KEY = "fx_eur_usd_unavailable"
    rate = cache.get(CACHE_KEY)
    if rate is not None:
        return rate

    if cache.get(UNAVAILABLE_KEY):
        return None

    try:
        resp = requests.get(
            settings.FRANKFURTER_API_URL,
            params={"from": "EUR", "to": "USD"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("rates", {}).get("USD")
        if rate:
            cache.set(CACHE_KEY, float(rate), timeout=6 * 3600)
            cache.delete(UNAVAILABLE_KEY)
            logger.info("EUR/USD rate: %s", rate)
            return float(rate)
    except Exception as e:
        logger.warning("Failed to fetch EUR/USD rate: %s", e)

    cache.set(UNAVAILABLE_KEY, True, timeout=15 * 60)
    return None


def snapshot_today_from_cache(instrument):
    """
    Persist today's price for an instrument from the live cache, if today
    isn't already snapshotted. Returns the PriceSnapshot or None.
    """
    from datetime import date as dt_date
    from decimal import Decimal

    from ..models import PriceSnapshot

    today = dt_date.today()
    if PriceSnapshot.objects.filter(instrument=instrument, date=today).exists():
        return None

    if instrument.kind == "etf":
        # ETFs use last_price (which is the cache mirror anyway).
        if instrument.last_price is None:
            return None
        price = instrument.last_price
        source = PriceSnapshot.Source.MANUAL
    else:
        live = cache.get(f"finnhub_{instrument.symbol}")
        if live is None:
            return None
        price = Decimal(str(live))
        source = PriceSnapshot.Source.CACHE

    return PriceSnapshot.objects.create(
        instrument=instrument,
        date=today,
        price=price,
        source=source,
    )


def _coingecko_id_for(symbol):
    """Best-effort symbol → CoinGecko coin id lookup, with cache."""
    cache_key = f"cg_id_{symbol.upper()}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    try:
        resp = requests.get(
            settings.COINGECKO_MARKETS_URL,
            params={"vs_currency": "usd", "symbols": symbol.lower(), "per_page": 5, "page": 1},
            timeout=10,
        )
        resp.raise_for_status()
        for coin in resp.json():
            if (coin.get("symbol") or "").upper() == symbol.upper():
                cache.set(cache_key, coin["id"], timeout=24 * 3600)
                return coin["id"]
    except Exception as e:
        logger.warning("CoinGecko id lookup failed for %s: %s", symbol, e)
    return None


def backfill_finnhub_stock_candles(instrument, days=365):
    """
    Pull daily OHLC from Finnhub for a stock instrument and write
    PriceSnapshot rows. Returns count written.

    Finnhub free tier may reject /stock/candle; we log and skip on 4xx.
    """
    import time
    from datetime import date as dt_date, timedelta
    from decimal import Decimal

    from ..models import PriceSnapshot

    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        return 0

    end = dt_date.today()
    start = end - timedelta(days=days)
    try:
        resp = requests.get(
            f"{settings.FINNHUB_REST_URL}/stock/candle",
            params={
                "symbol": instrument.finnhub_symbol or instrument.symbol,
                "resolution": "D",
                "from": int(time.mktime(start.timetuple())),
                "to": int(time.mktime(end.timetuple())),
                "token": api_key,
            },
            timeout=20,
        )
        if resp.status_code == 403 or resp.status_code == 401:
            logger.warning(
                "Finnhub /stock/candle denied for %s (likely free-tier limitation)",
                instrument.symbol,
            )
            return 0
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Finnhub candle fetch failed for %s: %s", instrument.symbol, e)
        return 0

    if data.get("s") != "ok":
        return 0

    closes = data.get("c", [])
    timestamps = data.get("t", [])
    if len(closes) != len(timestamps):
        return 0

    written = 0
    for ts, close in zip(timestamps, closes):
        d = dt_date.fromtimestamp(ts)
        try:
            _, created = PriceSnapshot.objects.update_or_create(
                instrument=instrument,
                date=d,
                defaults={
                    "price": Decimal(str(close)),
                    "source": PriceSnapshot.Source.FINNHUB,
                },
            )
            if created:
                written += 1
        except Exception as e:
            logger.warning("Snapshot write failed for %s @ %s: %s", instrument.symbol, d, e)
    return written


def backfill_coingecko_crypto(instrument, days=365):
    """
    Pull daily prices from CoinGecko for a crypto instrument. Returns count
    written. Free tier supports up to 365 days.
    """
    from datetime import date as dt_date, datetime, timezone as dt_tz
    from decimal import Decimal

    from ..models import PriceSnapshot

    coin_id = _coingecko_id_for(instrument.symbol)
    if not coin_id:
        return 0

    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": min(days, 365), "interval": "daily"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("CoinGecko chart fetch failed for %s: %s", instrument.symbol, e)
        return 0

    written = 0
    seen_dates = set()
    for ts_ms, price in data.get("prices", []):
        d = datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc).date()
        if d in seen_dates:
            continue
        seen_dates.add(d)
        try:
            _, created = PriceSnapshot.objects.update_or_create(
                instrument=instrument,
                date=d,
                defaults={
                    "price": Decimal(str(price)),
                    "source": PriceSnapshot.Source.COINGECKO,
                },
            )
            if created:
                written += 1
        except Exception as e:
            logger.warning("Snapshot write failed for %s @ %s: %s", instrument.symbol, d, e)
    return written


def run_price_snapshot_catchup(backfill_days=30, throttle_seconds=6):
    """
    Idempotent catchup task. For every instrument, ensure today is
    snapshotted. If recent days are missing (PC was off), try to backfill
    from the appropriate API.

    `throttle_seconds` controls the pause between API calls so we don't
    trip CoinGecko's free-tier rate limit (~10-30 req/min).

    Called periodically from the Celery price-stream worker so a missed
    midnight gets caught up the next time the machine is alive.
    """
    import time
    from datetime import date as dt_date, timedelta

    from ..models import Instrument, PriceSnapshot

    today = dt_date.today()
    written = 0
    api_calls = 0  # how many backfill API requests we've issued

    for inst in Instrument.objects.all():
        # 1. Today's snapshot from cache (no network).
        snap = snapshot_today_from_cache(inst)
        if snap:
            written += 1

        # 2. Backfill any historical gap. Skip ETFs (no API source).
        if inst.kind == "etf":
            continue

        latest = (
            PriceSnapshot.objects.filter(instrument=inst, date__lt=today)
            .order_by("-date")
            .first()
        )
        oldest_needed = today - timedelta(days=backfill_days)
        gap_start = (latest.date + timedelta(days=1)) if latest else oldest_needed
        if gap_start > today - timedelta(days=1):
            continue

        gap_days = (today - gap_start).days
        if gap_days <= 0:
            continue

        if api_calls > 0:
            time.sleep(throttle_seconds)

        if inst.kind == "stock":
            written += backfill_finnhub_stock_candles(inst, days=min(gap_days + 5, 365))
        elif inst.kind == "crypto":
            written += backfill_coingecko_crypto(inst, days=min(gap_days + 5, 365))
        api_calls += 1

    if written:
        logger.info("Price snapshot catchup wrote %d rows", written)
    return written


def lookup_instrument(kind, symbol):
    """
    Probe Finnhub (and CoinGecko for crypto names) to verify that a symbol
    exists and resolve its canonical name + current price.

    Returns one of:
      {"valid": True, "name": str, "symbol": str, "finnhub_symbol": str,
       "current_price": float}
      {"valid": False, "error": str}

    Stocks: `/stock/profile2` + `/quote`. Both must return data.
    Crypto: scoped to Binance USDT pairs (matches existing `BINANCE:XYZUSDT`
    convention). Finnhub `/quote?symbol=BINANCE:{X}USDT` for the price;
    CoinGecko `/coins/markets` for the human-readable name.
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        return {"valid": False, "error": "FINNHUB_API_KEY not configured."}

    symbol = symbol.strip().upper()
    if not symbol:
        return {"valid": False, "error": "Symbol is required."}

    if kind == "stock":
        try:
            profile = requests.get(
                f"{settings.FINNHUB_REST_URL}/stock/profile2",
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            profile.raise_for_status()
            pdata = profile.json()
        except Exception as e:
            logger.warning("Finnhub profile lookup failed for %s: %s", symbol, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        name = pdata.get("name")
        if not name:
            return {
                "valid": False,
                "error": f"'{symbol}' not found on Finnhub. Check the ticker.",
            }

        try:
            quote = requests.get(
                f"{settings.FINNHUB_REST_URL}/quote",
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            quote.raise_for_status()
            qdata = quote.json()
        except Exception as e:
            logger.warning("Finnhub quote lookup failed for %s: %s", symbol, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        price = qdata.get("c")
        if not price or price <= 0:
            return {
                "valid": False,
                "error": f"Finnhub has no live price for '{symbol}'.",
            }

        return {
            "valid": True,
            "name": name,
            "symbol": symbol,
            "finnhub_symbol": symbol,
            "current_price": float(price),
        }

    if kind == "crypto":
        finnhub_sym = f"BINANCE:{symbol}USDT"
        try:
            quote = requests.get(
                f"{settings.FINNHUB_REST_URL}/quote",
                params={"symbol": finnhub_sym, "token": api_key},
                timeout=10,
            )
            quote.raise_for_status()
            qdata = quote.json()
        except Exception as e:
            logger.warning("Finnhub crypto quote failed for %s: %s", finnhub_sym, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        price = qdata.get("c")
        if not price or price <= 0:
            return {
                "valid": False,
                "error": (
                    f"'{symbol}' not found as a Binance USDT pair on Finnhub."
                ),
            }

        # Resolve canonical name from CoinGecko (best-effort).
        name = symbol
        try:
            cg = requests.get(
                settings.COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "symbols": symbol.lower(),
                    "per_page": 5,
                    "page": 1,
                },
                timeout=10,
            )
            cg.raise_for_status()
            for coin in cg.json():
                if (coin.get("symbol") or "").upper() == symbol:
                    name = coin.get("name") or symbol
                    break
        except Exception as e:
            logger.warning("CoinGecko name lookup failed for %s: %s", symbol, e)

        return {
            "valid": True,
            "name": name,
            "symbol": symbol,
            "finnhub_symbol": finnhub_sym,
            "current_price": float(price),
        }

    return {"valid": False, "error": f"Unsupported kind '{kind}'."}


def refresh_instrument_last_price(instrument):
    """
    Mirror the most recent transaction's price onto the master Instrument.

    Picks the latest by (date, pk) across all users so historical inserts/edits
    don't clobber a more recent price. Used after creating/editing ETF
    transactions where `last_price` drives savings-plan execution.
    """
    latest = instrument.transactions.order_by("-date", "-pk").first()
    new_price = latest.price if latest else None
    if new_price != instrument.last_price:
        instrument.last_price = new_price
        instrument.save(update_fields=["last_price"])
