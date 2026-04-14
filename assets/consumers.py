import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache


class PriceConsumer(AsyncWebsocketConsumer):
    GROUP_NAME = "price_updates"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

        prices = await self._get_cached_prices()
        if prices:
            await self.send(text_data=json.dumps({"type": "price_update", "prices": prices}))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def price_update(self, event):
        await self.send(text_data=json.dumps(event))

    @sync_to_async
    def _get_cached_prices(self):
        from assets.models import Crypto, Stock

        prices = {}
        for symbol in Crypto.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True):
            price = cache.get(f"finnhub_{symbol}")
            if price is not None:
                prices[symbol] = price
        for symbol in Stock.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True):
            price = cache.get(f"finnhub_{symbol}")
            if price is not None:
                prices[symbol] = price
        return prices
