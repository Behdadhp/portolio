import json
import logging
import time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

import websocket

logger = logging.getLogger(__name__)

FINNHUB_WS_URL = "wss://ws.finnhub.io?token={}"
BROADCAST_INTERVAL = 1   # seconds — throttle browser updates to once per second per symbol
BACKOFF_INITIAL = 1      # first retry wait in seconds
BACKOFF_MAX = 60         # maximum retry wait in seconds
SYNC_INTERVAL = 5        # seconds — how often to check for new symbols
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


def _broadcast_price(short, price):
    """Send price update to all connected WebSocket clients via channel layer."""
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
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        logger.error("FINNHUB_API_KEY is not set.")
        return

    symbol_map = _build_symbol_map()
    if not symbol_map:
        logger.warning("No symbols with finnhub_symbol set in Crypto or Stock tables.")
        return

    # Clear any stale flag
    cache.delete(SYMBOLS_CHANGED_KEY)

    last_broadcast = {}   # short -> timestamp of last broadcast
    last_sync_check = [0]  # mutable so inner function can update it
    backoff = BACKOFF_INITIAL

    def _check_for_new_symbols(ws):
        """If symbols changed flag is set, subscribe to any new symbols."""
        now = time.time()
        if now - last_sync_check[0] < SYNC_INTERVAL:
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
                if now - last_broadcast.get(short, 0) >= BROADCAST_INTERVAL:
                    last_broadcast[short] = now
                    _broadcast_price(short, price)
                    logger.info("%s price updated: %s", short, price)

    def on_error(ws, error):
        logger.error("Finnhub WebSocket error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        logger.warning("Finnhub WebSocket closed: %s %s", close_status_code, close_msg)

    def on_open(ws):
        nonlocal backoff
        backoff = BACKOFF_INITIAL  # reset backoff on successful connection
        for finnhub_symbol in symbol_map:
            ws.send(json.dumps({"type": "subscribe", "symbol": finnhub_symbol}))
            logger.info("Subscribed to %s", finnhub_symbol)

    url = FINNHUB_WS_URL.format(api_key)

    while True:
        ws = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        ws.run_forever()

        # Connection dropped — wait and retry
        logger.info("Reconnecting in %s seconds...", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)
