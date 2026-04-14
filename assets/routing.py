from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/prices/", consumers.PriceConsumer.as_asgi()),
]
