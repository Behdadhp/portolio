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


def compute_analytics(transactions, symbol):
    """
    Compute portfolio analytics from a chronologically ordered list of transactions.

    Uses weighted-average cost basis: buys increase cost basis, sells reduce
    units but do NOT change the average (cost basis reduced proportionally).

    Returns a dict with all analytics, or None if no holdings.
    """
    cost_basis = 0.0
    units = 0.0

    total_invested = 0.0
    total_sold_value = 0.0
    total_sold_units = 0.0

    for tx in transactions.order_by("date", "pk"):
        amt = float(tx.amount)
        px = float(tx.price)

        if tx.status == "bought":
            cost_basis += amt * px
            units += amt
            total_invested += amt * px
        elif tx.status == "sold":
            if units > 0:
                avg = cost_basis / units
                cost_basis -= amt * avg
                units -= amt
            total_sold_value += amt * px
            total_sold_units += amt

    if units <= 0:
        return None

    avg_price = cost_basis / units
    current_price = cache.get(f"finnhub_{symbol}")

    analytics = {
        "avg_price": round(avg_price, 2),
        "units": round(units, 6),
        "cost_basis": round(cost_basis, 2),
        "total_invested": round(total_invested, 2),
        "total_sold_value": round(total_sold_value, 2),
        "realized_pnl": round(total_sold_value - total_sold_units * avg_price, 2) if total_sold_units > 0 else 0.0,
        "current_price": None,
        "current_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "sell_25": None,
        "sell_50": None,
        "sell_75": None,
        "buy_avg_minus_20": None,
    }

    if current_price is not None:
        cp = float(current_price)
        current_value = units * cp
        unrealized_pnl = current_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        analytics["current_price"] = round(cp, 2)
        analytics["current_value"] = round(current_value, 2)
        analytics["unrealized_pnl"] = round(unrealized_pnl, 2)
        analytics["unrealized_pnl_pct"] = round(unrealized_pnl_pct, 2)

        # Sell prices for +25%, +50%, +75% profit
        analytics["sell_25"] = round(avg_price * 1.25, 2)
        analytics["sell_50"] = round(avg_price * 1.50, 2)
        analytics["sell_75"] = round(avg_price * 1.75, 2)

        # Price to buy 1 unit to decrease average by 20%
        # New avg = (cost_basis + buy_price) / (units + 1) = avg_price * 0.8
        # buy_price = avg_price * 0.8 * (units + 1) - cost_basis
        target_avg = avg_price * 0.80
        buy_price_for_minus_20 = target_avg * (units + 1) - cost_basis
        analytics["buy_avg_minus_20"] = round(buy_price_for_minus_20, 2) if buy_price_for_minus_20 > 0 else 0.0


    return analytics


def load_live_prices(model):
    """Load cached live prices and market caps for tracked symbols of a model."""
    result = []
    for symbol in model.objects.exclude(finnhub_symbol="").values_list("symbol", flat=True):
        price = cache.get(f"finnhub_{symbol}")
        mcap = cache.get(f"finnhub_{symbol}_mcap")
        result.append({"short": symbol, "price": price, "market_cap": mcap or 0})
    result.sort(key=lambda x: x["market_cap"], reverse=True)
    return result
