import math

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, F, FloatField, Max, Min, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CryptoAssetForm, StockAssetForm
from .models import Crypto, CryptoAsset, Stock, StockAsset

ALLOWED_PER_PAGE = [20, 40]
DEFAULT_PER_PAGE = 20


def _get_filter_ranges(queryset):
    """
    Returns the min/max bounds for price and amount from the full
    (unfiltered) queryset so the range sliders know their limits.
    """
    agg = queryset.aggregate(
        price_min=Min("price"),
        price_max=Max("price"),
        amount_min=Min("amount"),
        amount_max=Max("amount"),
    )
    return {
        "price_min_bound": float(agg["price_min"] or 0),
        "price_max_bound": float(agg["price_max"] or 0),
        "amount_min_bound": float(agg["amount_min"] or 0),
        "amount_max_bound": float(agg["amount_max"] or 0),
    }


def _apply_filters(request, queryset):
    """
    Applies filters from query params and returns (filtered_qs, active_filters dict).
    Query params: date_from, date_to, price_min, price_max, amount_min, amount_max, status
    """
    filters = {}

    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if date_from:
        queryset = queryset.filter(date__gte=date_from)
        filters["date_from"] = date_from
    if date_to:
        queryset = queryset.filter(date__lte=date_to)
        filters["date_to"] = date_to

    price_min = request.GET.get("price_min", "")
    price_max = request.GET.get("price_max", "")
    if price_min:
        queryset = queryset.filter(price__gte=price_min)
        filters["price_min"] = price_min
    if price_max:
        queryset = queryset.filter(price__lte=price_max)
        filters["price_max"] = price_max

    amount_min = request.GET.get("amount_min", "")
    amount_max = request.GET.get("amount_max", "")
    if amount_min:
        queryset = queryset.filter(amount__gte=amount_min)
        filters["amount_min"] = amount_min
    if amount_max:
        queryset = queryset.filter(amount__lte=amount_max)
        filters["amount_max"] = amount_max

    status = request.GET.get("status", "")
    if status in ("bought", "sold"):
        queryset = queryset.filter(status=status)
        filters["status"] = status

    return queryset, filters


def _sort_and_paginate(request, queryset, allowed_sort_fields):
    """
    Applies sorting and pagination to a queryset based on query params.
    - ?sort=<field>       column to sort by
    - ?order=asc|desc     sort direction (default asc)
    - ?per_page=20|40     items per page
    - ?page=<n>           page number
    Returns (page_obj, current_sort, current_order, per_page).
    """
    sort = request.GET.get("sort", "")
    order = request.GET.get("order", "asc")

    if sort in allowed_sort_fields:
        order_prefix = "-" if order == "desc" else ""
        queryset = queryset.order_by(f"{order_prefix}{sort}")

    per_page = request.GET.get("per_page", DEFAULT_PER_PAGE)
    try:
        per_page = int(per_page)
        if per_page not in ALLOWED_PER_PAGE:
            per_page = DEFAULT_PER_PAGE
    except (ValueError, TypeError):
        per_page = DEFAULT_PER_PAGE

    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return page_obj, sort, order, per_page


def _get_asset_summary(queryset, name_field, symbol_field):
    """
    Groups assets by name and calculates the net total amount for each.
    Bought transactions count as +, sold transactions count as -.
    """
    return (
        queryset
        .values(name=F(name_field), symbol=F(symbol_field))
        .annotate(
            total=Coalesce(
                Sum(
                    Case(
                        When(status="bought", then=F("amount")),
                        When(status="sold", then=F("amount") * Value(-1.0)),
                        output_field=FloatField(),
                    )
                ),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        .order_by("name")
    )


# ── Stock views ──────────────────────────────────────────────

@login_required
def stock_list_view(request):
    stocks = _get_asset_summary(
        StockAsset.objects.filter(user=request.user),
        "stock__name",
        "stock__symbol",
    )
    return render(request, "assets/stock_list.html", {"stocks": stocks})


STOCK_SORT_FIELDS = ["date", "price", "amount", "status"]
DETAIL_COLUMNS = [("date", "Date"), ("price", "Price ($)"), ("amount", "Amount"), ("status", "Status")]


@login_required
def stock_detail_view(request, symbol):
    stock = get_object_or_404(Stock, symbol=symbol)
    base_qs = StockAsset.objects.filter(user=request.user, stock=stock)

    summary = _get_asset_summary(base_qs, "stock__name", "stock__symbol").first()
    total = summary["total"] if summary else 0

    ranges = _get_filter_ranges(base_qs)
    transactions, filters = _apply_filters(request, base_qs.order_by("-date"))

    page_obj, current_sort, current_order, per_page = _sort_and_paginate(
        request, transactions, STOCK_SORT_FIELDS
    )

    return render(
        request,
        "assets/stock_detail.html",
        {
            "page_obj": page_obj,
            "stock": stock,
            "total": total,
            "current_sort": current_sort,
            "current_order": current_order,
            "per_page": per_page,
            "filters": filters,
            "columns": DETAIL_COLUMNS,
            **ranges,
        },
    )


@login_required
def stock_edit_view(request, pk):
    transaction = get_object_or_404(StockAsset, pk=pk, user=request.user)
    form = StockAssetForm(instance=transaction)

    if request.method == "POST":
        form = StockAssetForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect("stock_detail", symbol=transaction.stock.symbol)

    return render(
        request,
        "assets/stock_edit.html",
        {"form": form, "transaction": transaction, "stock": transaction.stock},
    )


@login_required
def stock_delete_view(request, pk):
    transaction = get_object_or_404(StockAsset, pk=pk, user=request.user)
    stock = transaction.stock

    if request.method == "POST":
        transaction.delete()
        if not StockAsset.objects.filter(user=request.user, stock=stock).exists():
            return redirect("stocks")
        return redirect("stock_detail", symbol=stock.symbol)

    return render(
        request,
        "assets/stock_delete.html",
        {"transaction": transaction, "stock": stock},
    )


@login_required
def stock_add_view(request, symbol=None):
    initial = {}
    stock_obj = None
    if symbol:
        stock_obj = get_object_or_404(Stock, symbol=symbol)
        initial["stock"] = stock_obj

    form = StockAssetForm(initial=initial)

    if request.method == "POST":
        form = StockAssetForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            return redirect("stock_detail", symbol=transaction.stock.symbol)

    return render(
        request,
        "assets/stock_add.html",
        {"form": form, "stock": stock_obj},
    )


# ── Crypto views ─────────────────────────────────────────────

@login_required
def crypto_list_view(request):
    cryptos = _get_asset_summary(
        CryptoAsset.objects.filter(user=request.user),
        "crypto__name",
        "crypto__symbol",
    )
    return render(request, "assets/crypto_list.html", {"cryptos": cryptos})




@login_required
def crypto_detail_view(request, symbol):
    crypto = get_object_or_404(Crypto, symbol=symbol)
    base_qs = CryptoAsset.objects.filter(user=request.user, crypto=crypto)

    summary = _get_asset_summary(base_qs, "crypto__name", "crypto__symbol").first()
    total = summary["total"] if summary else 0

    ranges = _get_filter_ranges(base_qs)
    transactions, filters = _apply_filters(request, base_qs.order_by("-date"))

    page_obj, current_sort, current_order, per_page = _sort_and_paginate(
        request, transactions, STOCK_SORT_FIELDS
    )

    return render(
        request,
        "assets/crypto_detail.html",
        {
            "page_obj": page_obj,
            "crypto": crypto,
            "total": total,
            "current_sort": current_sort,
            "current_order": current_order,
            "per_page": per_page,
            "filters": filters,
            "columns": DETAIL_COLUMNS,
            **ranges,
        },
    )


@login_required
def crypto_add_view(request, symbol=None):
    initial = {}
    crypto_obj = None
    if symbol:
        crypto_obj = get_object_or_404(Crypto, symbol=symbol)
        initial["crypto"] = crypto_obj

    form = CryptoAssetForm(initial=initial)

    if request.method == "POST":
        form = CryptoAssetForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            return redirect("crypto_detail", symbol=transaction.crypto.symbol)

    return render(
        request,
        "assets/crypto_add.html",
        {"form": form, "crypto": crypto_obj},
    )


@login_required
def crypto_edit_view(request, pk):
    transaction = get_object_or_404(CryptoAsset, pk=pk, user=request.user)
    form = CryptoAssetForm(instance=transaction)

    if request.method == "POST":
        form = CryptoAssetForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect("crypto_detail", symbol=transaction.crypto.symbol)

    return render(
        request,
        "assets/crypto_edit.html",
        {"form": form, "transaction": transaction, "crypto": transaction.crypto},
    )


@login_required
def crypto_delete_view(request, pk):
    transaction = get_object_or_404(CryptoAsset, pk=pk, user=request.user)
    crypto = transaction.crypto

    if request.method == "POST":
        transaction.delete()
        if not CryptoAsset.objects.filter(user=request.user, crypto=crypto).exists():
            return redirect("crypto")
        return redirect("crypto_detail", symbol=crypto.symbol)

    return render(
        request,
        "assets/crypto_delete.html",
        {"transaction": transaction, "crypto": crypto},
    )
