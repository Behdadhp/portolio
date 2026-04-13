from django.contrib import admin

from .models import Crypto, CryptoAsset, Stock, StockAsset


@admin.register(Crypto)
class CryptoAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol")
    search_fields = ("name", "symbol")


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol")
    search_fields = ("name", "symbol")


@admin.register(CryptoAsset)
class CryptoAssetAdmin(admin.ModelAdmin):
    list_display = ("crypto", "user", "price", "amount", "date", "status")
    list_filter = ("status",)
    search_fields = ("crypto__name", "crypto__symbol", "user__email")


@admin.register(StockAsset)
class StockAssetAdmin(admin.ModelAdmin):
    list_display = ("stock", "user", "price", "amount", "date", "status")
    list_filter = ("status",)
    search_fields = ("stock__name", "stock__symbol", "user__email")
