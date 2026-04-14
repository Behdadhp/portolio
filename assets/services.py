from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, F, FloatField, Max, Min, Sum, Value, When
from django.db.models.functions import Coalesce

ALLOWED_PER_PAGE = [20, 40]
DEFAULT_PER_PAGE = 20
DETAIL_SORT_FIELDS = ["date", "price", "amount", "status"]
DETAIL_COLUMNS = [
    ("date", "Date"),
    ("price", "Price ($)"),
    ("amount", "Amount"),
    ("status", "Status"),
]


def get_filter_ranges(queryset):
    """Return min/max bounds for price and amount sliders."""
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


def apply_filters(request, queryset):
    """Apply query-param filters and return (filtered_qs, active_filters dict)."""
    filters = {}
    params = {
        "date_from": ("date__gte", str),
        "date_to": ("date__lte", str),
        "price_min": ("price__gte", str),
        "price_max": ("price__lte", str),
        "amount_min": ("amount__gte", str),
        "amount_max": ("amount__lte", str),
    }
    for param, (lookup, cast) in params.items():
        value = request.GET.get(param, "")
        if value:
            queryset = queryset.filter(**{lookup: cast(value)})
            filters[param] = value

    status = request.GET.get("status", "")
    if status in ("bought", "sold"):
        queryset = queryset.filter(status=status)
        filters["status"] = status

    return queryset, filters


def sort_and_paginate(request, queryset, allowed_sort_fields=None):
    """Apply sorting and pagination. Returns (page_obj, sort, order, per_page)."""
    if allowed_sort_fields is None:
        allowed_sort_fields = DETAIL_SORT_FIELDS

    sort = request.GET.get("sort", "")
    order = request.GET.get("order", "asc")

    if sort in allowed_sort_fields:
        prefix = "-" if order == "desc" else ""
        queryset = queryset.order_by(f"{prefix}{sort}")

    per_page = request.GET.get("per_page", DEFAULT_PER_PAGE)
    try:
        per_page = int(per_page)
        if per_page not in ALLOWED_PER_PAGE:
            per_page = DEFAULT_PER_PAGE
    except (ValueError, TypeError):
        per_page = DEFAULT_PER_PAGE

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return page_obj, sort, order, per_page


def get_asset_summary(queryset, name_field, symbol_field):
    """Group assets by name and calculate net total amount (bought=+, sold=-)."""
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


def load_live_prices(model):
    """Load cached live prices and market caps for tracked symbols of a model."""
    result = []
    for symbol in model.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True):
        price = cache.get(f"finnhub_{symbol}")
        mcap = cache.get(f"finnhub_{symbol}_mcap")
        result.append({"short": symbol, "price": price, "market_cap": mcap or 0})
    result.sort(key=lambda x: x["market_cap"], reverse=True)
    return result
