import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache


class PriceConsumer(AsyncWebsocketConsumer):
    GROUP_NAME = "price_updates"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

        data = await self._get_cached_data()
        if data["prices"]:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "price_update",
                        "prices": data["prices"],
                        "market_caps": data["market_caps"],
                    }
                )
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def price_update(self, event):
        await self.send(text_data=json.dumps(event))

    @sync_to_async
    def _get_cached_data(self):
        from assets.models import Crypto, Stock

        prices = {}
        market_caps = {}
        for model in (Crypto, Stock):
            for symbol in model.objects.exclude(finnhub_symbol="").values_list(
                "symbol", flat=True
            ):
                price = cache.get(f"finnhub_{symbol}")
                mcap = cache.get(f"finnhub_{symbol}_mcap")
                if price is not None:
                    prices[symbol] = price
                if mcap is not None:
                    market_caps[symbol] = mcap
        return {"prices": prices, "market_caps": market_caps}
