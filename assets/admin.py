from django.contrib import admin

from .models import (
    CashFlow,
    ETFSavingsPlan,
    Instrument,
    PriceAlert,
    Transaction,
)


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "kind", "finnhub_symbol", "last_price", "date_added")
    list_filter = ("kind",)
    search_fields = ("name", "symbol")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("instrument", "user", "price", "amount", "date", "status")
    list_filter = ("status", "instrument__kind")
    search_fields = ("instrument__name", "instrument__symbol", "user__email")


@admin.register(ETFSavingsPlan)
class ETFSavingsPlanAdmin(admin.ModelAdmin):
    list_display = (
        "instrument",
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
    search_fields = ("instrument__name", "instrument__symbol", "user__email")
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
    search_fields = ("user__email", "instrument__symbol", "instrument__name")
    readonly_fields = ("created_at",)
