from django.contrib import admin

from .models import (
    ETF,
    CashFlow,
    Crypto,
    CryptoAsset,
    ETFAsset,
    ETFSavingsPlan,
    PriceAlert,
    Stock,
    StockAsset,
)


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


@admin.register(ETF)
class ETFAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "last_price", "date_added")
    search_fields = ("name", "symbol")


@admin.register(ETFAsset)
class ETFAssetAdmin(admin.ModelAdmin):
    list_display = ("etf", "user", "price", "amount", "date", "status")
    list_filter = ("status",)
    search_fields = ("etf__name", "etf__symbol", "user__email")


@admin.register(ETFSavingsPlan)
class ETFSavingsPlanAdmin(admin.ModelAdmin):
    list_display = (
        "etf",
        "user",
        "amount",
        "currency",
        "interval",
        "start_date",
        "next_execution_date",
        "last_executed_at",
        "active",
    )
    list_filter = ("interval", "currency", "active")
    search_fields = ("etf__name", "etf__symbol", "user__email")
    readonly_fields = ("created_at", "last_executed_at")


@admin.register(CashFlow)
class CashFlowAdmin(admin.ModelAdmin):
    list_display = ("user", "direction", "amount_usd", "date", "note", "created_at")
    list_filter = ("direction",)
    search_fields = ("user__email", "note")
    readonly_fields = ("created_at",)


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "symbol",
        "target_price",
        "direction",
        "email_sent",
        "created_at",
    )
    list_filter = ("direction", "email_sent")
    search_fields = ("user__email", "stock__symbol", "crypto__symbol", "etf__symbol")
    readonly_fields = ("created_at",)
