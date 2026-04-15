from django.contrib import admin

from .models import Crypto, CryptoAsset, PriceAlert, Stock, StockAsset


@admin.register(Crypto)
class CryptoAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "finnhub_symbol", "date_added")
    search_fields = ("name", "symbol")


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "finnhub_symbol", "date_added")
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


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "symbol", "target_price", "direction", "email_sent", "created_at")
    list_filter = ("direction", "email_sent")
    search_fields = ("user__email", "stock__symbol", "crypto__symbol")
    readonly_fields = ("created_at",)
