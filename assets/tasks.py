import json
import logging
import threading
import time

import requests
import websocket
from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from .services import sync_alert_cache

logger = logging.getLogger(__name__)

SYMBOLS_CHANGED_KEY = "finnhub_symbols_changed"


def _build_symbol_map():
    """Build lookup from Crypto and Stock tables: finnhub_symbol -> symbol."""
    from assets.models import Crypto, Stock

    symbol_map = {}
    for finnhub, short in Crypto.objects.exclude(finnhub_symbol="").values_list(
        "finnhub_symbol", "symbol"
    ):
        symbol_map[finnhub] = short
    for finnhub, short in Stock.objects.exclude(finnhub_symbol="").values_list(
        "finnhub_symbol", "symbol"
    ):
        symbol_map[finnhub] = short
    return symbol_map


def _fetch_market_caps():
    """Fetch market caps from Finnhub (stocks) and CoinGecko (crypto), store in cache."""
    from assets.models import Crypto, Stock

    api_key = settings.FINNHUB_API_KEY

    # Stocks — Finnhub /stock/profile2
    for finnhub_sym, short in Stock.objects.exclude(finnhub_symbol="").values_list(
        "finnhub_symbol", "symbol"
    ):
        try:
            resp = requests.get(
                f"{settings.FINNHUB_REST_URL}/stock/profile2",
                params={"symbol": finnhub_sym, "token": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            mcap = data.get("marketCapitalization")
            if mcap:
                # Finnhub returns market cap in millions
                cache.set(f"finnhub_{short}_mcap", mcap * 1_000_000, timeout=None)
                logger.info("%s market cap: $%.0fM", short, mcap)
        except Exception as e:
            logger.warning("Failed to fetch market cap for %s: %s", short, e)

    # Crypto — CoinGecko /coins/markets (free, no key needed)
    crypto_symbols = set(
        Crypto.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True)
    )
    if not crypto_symbols:
        return

    try:
        resp = requests.get(
            settings.COINGECKO_MARKETS_URL,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        for coin in resp.json():
            coin_symbol = coin.get("symbol", "").upper()
            if coin_symbol in crypto_symbols:
                mcap = coin.get("market_cap")
                if mcap:
                    cache.set(f"finnhub_{coin_symbol}_mcap", mcap, timeout=None)
                    logger.info("%s market cap: $%.0f", coin_symbol, mcap)
    except Exception as e:
        logger.warning("Failed to fetch crypto market caps: %s", e)


def _poll_stock_quotes():
    """Fetch latest stock quotes via REST API (free tier has no real-time WS for US stocks)."""
    from assets.models import Stock

    api_key = settings.FINNHUB_API_KEY
    for finnhub_sym, short in Stock.objects.exclude(finnhub_symbol="").values_list(
        "finnhub_symbol", "symbol"
    ):
        try:
            resp = requests.get(
                f"{settings.FINNHUB_REST_URL}/quote",
                params={"symbol": finnhub_sym, "token": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            price = data.get("c")  # current price
            if price:
                old_price = cache.get(f"finnhub_{short}")
                cache.set(f"finnhub_{short}", price, timeout=None)
                _check_price_alerts(short, price)
                if old_price != price:
                    _broadcast(short, price)
                    logger.info("REST poll %s (%s): $%s", short, finnhub_sym, price)
        except Exception as e:
            logger.warning("Failed to poll quote for %s: %s", short, e)


def _stock_quote_loop():
    """Background thread that polls stock quotes every 15 seconds."""
    while True:
        try:
            _poll_stock_quotes()
        except Exception as e:
            logger.warning("Stock quote poll error: %s", e)
        time.sleep(settings.STOCK_QUOTE_INTERVAL)


def _market_cap_loop():
    """Background thread that refreshes market caps periodically."""
    while True:
        try:
            _fetch_market_caps()
        except Exception as e:
            logger.warning("Market cap refresh error: %s", e)
        time.sleep(settings.MARKET_CAP_REFRESH)


def _send_alert_email(alert, current_price):
    """Send price alert email to the user. Runs in a thread to avoid blocking price ticks."""
    try:
        from django.core.mail import send_mail
        from django.template.loader import render_to_string

        user = alert.user
        is_stock = alert.stock_id is not None
        symbol = alert.symbol
        asset_type_path = "stocks" if is_stock else "crypto"
        detail_url = f"{settings.SITE_URL}/{asset_type_path}/{symbol}/"

        invest_amount_str = None
        invest_units_str = None
        if alert.direction == "below" and alert.invest_amount is not None:
            invest_amount_str = f"{alert.invest_amount:,.2f}"
            if current_price and current_price > 0:
                invest_units_str = (
                    f"{float(alert.invest_amount) / float(current_price):,.6f}"
                )

        context = {
            "first_name": user.first_name,
            "asset_name": alert.asset_name,
            "symbol": symbol,
            "target_price": f"{alert.target_price:,.2f}",
            "current_price": f"{current_price:,.2f}",
            "direction": alert.direction,
            "invest_amount": invest_amount_str,
            "invest_units": invest_units_str,
            "detail_url": detail_url,
        }

        subject = f"Price Alert: {symbol} {'above' if alert.direction == 'above' else 'below'} ${alert.target_price:,.2f}"
        html_body = render_to_string("emails/price_alert.html", context)
        text_body = render_to_string("emails/price_alert.txt", context)

        send_mail(
            subject=subject,
            message=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=False,
        )
        logger.info(
            "Alert email sent to %s for %s @ $%.2f", user.email, symbol, current_price
        )
    except Exception as e:
        logger.error("Failed to send alert email for alert %s: %s", alert.id, e)


def _check_price_alerts(short, price):
    """Check if any active price alerts should trigger for this symbol/price."""
    alert_data = cache.get("price_alerts_active")
    if not alert_data:
        return

    alerts_for_symbol = alert_data.get(short, [])
    if not alerts_for_symbol:
        return

    triggered_ids = []
    for alert in alerts_for_symbol:
        target = alert["target_price"]
        direction = alert["direction"]
        if (direction == "above" and price >= target) or (
            direction == "below" and price <= target
        ):
            triggered_ids.append(alert["id"])
            logger.info(
                "ALERT TRIGGERED: %s %s $%.2f (actual: $%.2f) for user %s",
                short,
                direction,
                target,
                price,
                alert["user_id"],
            )

    if triggered_ids:
        # Mark as triggered in the DB
        from assets.models import PriceAlert

        triggered_alerts = list(
            PriceAlert.objects.filter(
                id__in=triggered_ids, email_sent=False
            ).select_related("user", "stock", "crypto")
        )
        PriceAlert.objects.filter(id__in=triggered_ids, email_sent=False).update(
            email_sent=True
        )

        # Send emails in background threads (don't block price processing)
        for alert in triggered_alerts:
            threading.Thread(
                target=_send_alert_email, args=(alert, price), daemon=True
            ).start()

        # Rebuild cache to remove triggered alerts
        sync_alert_cache()


def _broadcast(short, price):
    """Send price update to all connected WebSocket clients."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "price_updates",
        {"type": "price_update", "prices": {short: price}},
    )


@shared_task
def stream_prices():
    """Connect to Finnhub WebSocket and stream prices for all tracked Crypto and Stock entries.

    Automatically reconnects with exponential backoff if the connection drops.
    Detects new symbols added to the database and subscribes without restart.
    Fetches market caps on startup and refreshes every 15 minutes.
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        logger.error("FINNHUB_API_KEY is not set.")
        return

    symbol_map = _build_symbol_map()
    if not symbol_map:
        logger.warning("No symbols with finnhub_symbol set in Crypto or Stock tables.")
        return

    # Fetch market caps on startup, then refresh in background
    _fetch_market_caps()
    mcap_thread = threading.Thread(target=_market_cap_loop, daemon=True)
    mcap_thread.start()

    # Load active price alerts into Redis cache
    sync_alert_cache()

    # Poll stock quotes via REST API (Finnhub free tier has no real-time WS for US stocks)
    _poll_stock_quotes()
    stock_poll_thread = threading.Thread(target=_stock_quote_loop, daemon=True)
    stock_poll_thread.start()

    # Clear any stale flag
    cache.delete(SYMBOLS_CHANGED_KEY)

    last_broadcast = {}
    last_sync_check = [0]
    backoff = settings.BACKOFF_INITIAL

    def _check_for_new_symbols(ws):
        """If symbols changed flag is set, subscribe to any new symbols."""
        now = time.time()
        if now - last_sync_check[0] < settings.SYNC_INTERVAL:
            return
        last_sync_check[0] = now

        if not cache.get(SYMBOLS_CHANGED_KEY):
            return

        cache.delete(SYMBOLS_CHANGED_KEY)
        updated_map = _build_symbol_map()
        new_symbols = set(updated_map) - set(symbol_map)
        for finnhub_symbol in new_symbols:
            short = updated_map[finnhub_symbol]
            symbol_map[finnhub_symbol] = short
            ws.send(json.dumps({"type": "subscribe", "symbol": finnhub_symbol}))
            logger.info(
                "New symbol detected — subscribed to %s (%s)", finnhub_symbol, short
            )

        # Refresh market caps to include new symbols
        if new_symbols:
            _fetch_market_caps()

    def on_message(ws, message):
        _check_for_new_symbols(ws)

        data = json.loads(message)
        if data.get("type") == "trade" and data.get("data"):
            latest_trade = data["data"][-1]
            symbol = latest_trade["s"]
            price = latest_trade["p"]
            short = symbol_map.get(symbol)
            if short:
                cache.set(f"finnhub_{short}", price, timeout=None)

                # Check price alerts (from Redis cache, no DB hit)
                _check_price_alerts(short, price)

                now = time.time()
                if now - last_broadcast.get(short, 0) >= settings.BROADCAST_INTERVAL:
                    last_broadcast[short] = now
                    _broadcast(short, price)
                    logger.info("%s price updated: %s", short, price)

    def on_error(ws, error):
        logger.error("Finnhub WebSocket error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        logger.warning("Finnhub WebSocket closed: %s %s", close_status_code, close_msg)

    def on_open(ws):
        nonlocal backoff
        backoff = settings.BACKOFF_INITIAL
        for finnhub_symbol in symbol_map:
            ws.send(json.dumps({"type": "subscribe", "symbol": finnhub_symbol}))
            logger.info("Subscribed to %s", finnhub_symbol)

    url = settings.FINNHUB_WS_URL.format(api_key)

    while True:
        ws = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        ws.run_forever(ping_interval=10, ping_timeout=5)

        # Connection dropped — wait and retry
        logger.info("Reconnecting in %s seconds...", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, settings.BACKOFF_MAX)
