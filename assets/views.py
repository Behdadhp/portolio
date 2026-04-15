from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CryptoAssetForm, StockAssetForm
from .models import Crypto, CryptoAsset, Stock, StockAsset
from .services import (
    DETAIL_COLUMNS,
    apply_filters,
    compute_analytics,
    compute_crypto_tax,
    compute_stock_tax,
    get_asset_summary,
    get_eur_usd_rate,
    get_filter_ranges,
    sort_and_paginate,
)


# ── Generic CRUD helpers ─────────────────────────────────────

def _list_view(request, transaction_model, name_field, symbol_field, template, context_key):
    import json

    summary = get_asset_summary(
        transaction_model.objects.filter(user=request.user),
        name_field,
        symbol_field,
    )
    enriched = []
    allocation = []
    for row in summary:
        price = cache.get(f"finnhub_{row['symbol']}")
        row["price"] = price
        row["worth"] = round(float(row["total"]) * float(price), 2) if price is not None else None
        enriched.append(row)
        worth = round(float(row["total"]) * float(price), 2) if price is not None and row["total"] > 0 else 0
        allocation.append({"label": row["name"], "symbol": row["symbol"], "value": worth})

    return render(request, template, {
        context_key: enriched,
        "allocation_json": json.dumps(allocation),
    })


def _detail_view(request, symbol, master_model, transaction_model, fk_field,
                 name_field, symbol_field, template, extra_context=None):
    master = get_object_or_404(master_model, symbol=symbol)
    base_qs = transaction_model.objects.filter(user=request.user, **{fk_field: master})

    summary = get_asset_summary(base_qs, name_field, symbol_field).first()
    total = summary["total"] if summary else 0

    analytics = compute_analytics(base_qs, symbol)

    ranges = get_filter_ranges(base_qs)
    transactions, filters = apply_filters(request, base_qs.order_by("-date"))
    page_obj, current_sort, current_order, per_page = sort_and_paginate(request, transactions)

    context = {
        "page_obj": page_obj,
        fk_field: master,
        "total": total,
        "analytics": analytics,
        "asset_symbol": symbol,
        "current_sort": current_sort,
        "current_order": current_order,
        "per_page": per_page,
        "filters": filters,
        "columns": DETAIL_COLUMNS,
        "eur_usd_rate": get_eur_usd_rate(),
        **ranges,
    }
    if extra_context:
        context.update(extra_context)
    return render(request, template, context)


def _add_view(request, form_class, master_model, fk_field, template, detail_url, symbol=None):
    initial = {}
    master = None
    if symbol:
        master = get_object_or_404(master_model, symbol=symbol)
        initial[fk_field] = master

    form = form_class(initial=initial)

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            return redirect(detail_url, symbol=getattr(transaction, fk_field).symbol)

    return render(request, template, {
        "form": form, fk_field: master, "eur_usd_rate": get_eur_usd_rate(),
    })


def _edit_view(request, pk, form_class, transaction_model, fk_field, template, detail_url):
    transaction = get_object_or_404(transaction_model, pk=pk, user=request.user)
    form = form_class(instance=transaction)

    if request.method == "POST":
        form = form_class(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect(detail_url, symbol=getattr(transaction, fk_field).symbol)

    master = getattr(transaction, fk_field)
    return render(request, template, {
        "form": form, "transaction": transaction, fk_field: master,
        "eur_usd_rate": get_eur_usd_rate(),
    })


def _delete_view(request, pk, transaction_model, fk_field, template, list_url, detail_url):
    transaction = get_object_or_404(transaction_model, pk=pk, user=request.user)
    master = getattr(transaction, fk_field)

    if request.method == "POST":
        transaction.delete()
        if not transaction_model.objects.filter(user=request.user, **{fk_field: master}).exists():
            return redirect(list_url)
        return redirect(detail_url, symbol=master.symbol)

    return render(request, template, {"transaction": transaction, fk_field: master})


# ── Stock views ──────────────────────────────────────────────

@login_required
def stock_list_view(request):
    return _list_view(
        request, StockAsset, "stock__name", "stock__symbol",
        "assets/stock_list.html", "stocks",
    )


@login_required
def stock_detail_view(request, symbol):
    tax = compute_stock_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request, symbol, Stock, StockAsset, "stock",
        "stock__name", "stock__symbol", "assets/stock_detail.html",
        extra_context={"tax": tax},
    )


@login_required
def stock_add_view(request, symbol=None):
    return _add_view(
        request, StockAssetForm, Stock, "stock",
        "assets/stock_add.html", "stock_detail", symbol,
    )


@login_required
def stock_edit_view(request, pk):
    return _edit_view(
        request, pk, StockAssetForm, StockAsset, "stock",
        "assets/stock_edit.html", "stock_detail",
    )


@login_required
def stock_delete_view(request, pk):
    return _delete_view(
        request, pk, StockAsset, "stock",
        "assets/stock_delete.html", "stocks", "stock_detail",
    )


# ── Crypto views ─────────────────────────────────────────────

@login_required
def crypto_list_view(request):
    return _list_view(
        request, CryptoAsset, "crypto__name", "crypto__symbol",
        "assets/crypto_list.html", "cryptos",
    )


@login_required
def crypto_detail_view(request, symbol):
    crypto_tax = compute_crypto_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request, symbol, Crypto, CryptoAsset, "crypto",
        "crypto__name", "crypto__symbol", "assets/crypto_detail.html",
        extra_context={"crypto_tax": crypto_tax},
    )


@login_required
def crypto_add_view(request, symbol=None):
    return _add_view(
        request, CryptoAssetForm, Crypto, "crypto",
        "assets/crypto_add.html", "crypto_detail", symbol,
    )


@login_required
def crypto_edit_view(request, pk):
    return _edit_view(
        request, pk, CryptoAssetForm, CryptoAsset, "crypto",
        "assets/crypto_edit.html", "crypto_detail",
    )


@login_required
def crypto_delete_view(request, pk):
    return _delete_view(
        request, pk, CryptoAsset, "crypto",
        "assets/crypto_delete.html", "crypto", "crypto_detail",
    )
