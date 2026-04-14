import json
import logging
import threading
import time

import requests
import websocket
from celery import shared_task
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SYMBOLS_CHANGED_KEY = "finnhub_symbols_changed"


def _build_symbol_map():
    """Build lookup from Crypto and Stock tables: finnhub_symbol -> symbol."""
    from assets.models import Crypto, Stock

    symbol_map = {}
    for finnhub, short in Crypto.objects.exclude(finnhub_symbol="").values_list("finnhub_symbol", "symbol"):
        symbol_map[finnhub] = short
    for finnhub, short in Stock.objects.exclude(finnhub_symbol="").values_list("finnhub_symbol", "symbol"):
        symbol_map[finnhub] = short
    return symbol_map


def _fetch_market_caps():
    """Fetch market caps from Finnhub (stocks) and CoinGecko (crypto), store in cache."""
    from assets.models import Crypto, Stock

    api_key = settings.FINNHUB_API_KEY

    # Stocks — Finnhub /stock/profile2
    for symbol in Stock.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True):
        try:
            resp = requests.get(
                f"{settings.FINNHUB_REST_URL}/stock/profile2",
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            data = resp.json()
            mcap = data.get("marketCapitalization")
            if mcap:
                # Finnhub returns market cap in millions
                cache.set(f"finnhub_{symbol}_mcap", mcap * 1_000_000, timeout=None)
                logger.info("%s market cap: $%.0fM", symbol, mcap)
        except Exception as e:
            logger.warning("Failed to fetch market cap for %s: %s", symbol, e)

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
        for coin in resp.json():
            coin_symbol = coin.get("symbol", "").upper()
            if coin_symbol in crypto_symbols:
                mcap = coin.get("market_cap")
                if mcap:
                    cache.set(f"finnhub_{coin_symbol}_mcap", mcap, timeout=None)
                    logger.info("%s market cap: $%.0f", coin_symbol, mcap)
    except Exception as e:
        logger.warning("Failed to fetch crypto market caps: %s", e)


def _market_cap_loop():
    """Background thread that refreshes market caps periodically."""
    while True:
        try:
            _fetch_market_caps()
        except Exception as e:
            logger.warning("Market cap refresh error: %s", e)
        time.sleep(settings.MARKET_CAP_REFRESH)


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
            logger.info("New symbol detected — subscribed to %s (%s)", finnhub_symbol, short)

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
