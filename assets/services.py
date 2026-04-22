import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, F, FloatField, Max, Min, Sum, Value, When
from django.db.models.functions import Coalesce

logger = logging.getLogger(__name__)

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
        queryset.values(name=F(name_field), symbol=F(symbol_field))
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

    for tx in transactions.order_by("date", "status", "pk"):
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
        return {
            "warning": "sold_more_than_bought" if units < 0 else "no_holdings",
            "units": round(units, 6),
            "total_invested": round(total_invested, 2),
            "total_sold_value": round(total_sold_value, 2),
            "realized_pnl": (
                round(
                    total_sold_value
                    - total_sold_units
                    * (total_invested / max(total_sold_units + units, 0.0001)),
                    2,
                )
                if total_sold_units > 0
                else 0.0
            ),
        }

    avg_price = cost_basis / units
    current_price = cache.get(f"finnhub_{symbol}")

    analytics = {
        "avg_price": round(avg_price, 2),
        "units": round(units, 6),
        "cost_basis": round(cost_basis, 2),
        "total_invested": round(total_invested, 2),
        "total_sold_value": round(total_sold_value, 2),
        "realized_pnl": (
            round(total_sold_value - total_sold_units * avg_price, 2)
            if total_sold_units > 0
            else 0.0
        ),
        "current_price": None,
        "current_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "sell_5": None,
        "sell_10": None,
        "sell_25": None,
        "buy_avg_minus_10": None,
        "buy_avg_minus_10_spend": None,
    }

    if current_price is not None:
        cp = float(current_price)
        current_value = units * cp
        unrealized_pnl = current_value - cost_basis
        unrealized_pnl_pct = (
            (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
        )

        analytics["current_price"] = round(cp, 2)
        analytics["current_value"] = round(current_value, 2)
        analytics["unrealized_pnl"] = round(unrealized_pnl, 2)
        analytics["unrealized_pnl_pct"] = round(unrealized_pnl_pct, 2)

        # Sell prices for +5%, +10%, +25% profit
        analytics["sell_5"] = round(avg_price * 1.05, 2)
        analytics["sell_10"] = round(avg_price * 1.10, 2)
        analytics["sell_25"] = round(avg_price * 1.25, 2)

        # Price to buy <units> more to decrease average by 10%
        # New avg = (cost_basis + units * buy_price) / (units * 2) = avg_price * 0.9
        # buy_price = (avg_price * 0.9 * units * 2 - cost_basis) / units
        target_avg = avg_price * 0.90
        buy_price_for_minus_10 = (target_avg * (units * 2) - cost_basis) / units
        analytics["buy_avg_minus_10"] = (
            round(buy_price_for_minus_10, 2) if buy_price_for_minus_10 > 0 else 0.0
        )
        # Dollar spend needed to achieve the -10% avg at that price
        # (buy <units> more at <buy_price_for_minus_10>).
        analytics["buy_avg_minus_10_spend"] = (
            round(buy_price_for_minus_10 * units, 2)
            if buy_price_for_minus_10 > 0
            else 0.0
        )

    return analytics


def compute_stock_tax(user, current_symbol=None):
    """
    Compute German stock tax analytics for the current year across all user stocks.

    German tax rules:
    - Kapitalertragsteuer: 25% on gains
    - Solidaritätszuschlag: 5.5% on the tax
    - Effective rate: 26.375% (without Kirchensteuer)
    - Freibetrag: 1,000 EUR/year (singles)
    - Stock losses can only offset stock gains

    Returns a dict with tax breakdown, or None if no sells this year.
    """
    from datetime import date
    from .models import StockAsset

    TAX_RATE = 0.26375  # 25% + 5.5% Soli
    FREIBETRAG_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIBETRAG = FREIBETRAG_EUR * eur_usd  # threshold in USD for comparison
    current_year = date.today().year

    all_stocks_qs = StockAsset.objects.filter(user=user)

    # Get unique stock FKs that have transactions
    stock_ids = all_stocks_qs.values_list("stock_id", flat=True).distinct()

    total_gains = 0.0
    total_losses = 0.0
    current_stock_gains = 0.0
    current_stock_losses = 0.0
    sell_count = 0

    for stock_id in stock_ids:
        txs = (
            all_stocks_qs.filter(stock_id=stock_id)
            .select_related("stock")
            .order_by("date", "status", "pk")
        )
        stock_symbol = None
        cost_basis = 0.0
        units = 0.0

        for tx in txs:
            if stock_symbol is None:
                stock_symbol = tx.stock.symbol
            amt = float(tx.amount)
            px = float(tx.price)

            if tx.status == "bought":
                cost_basis += amt * px
                units += amt
            elif tx.status == "sold":
                if units > 0:
                    avg = cost_basis / units
                    pnl = (px - avg) * amt
                    cost_basis -= amt * avg
                    units -= amt

                    if tx.date.year == current_year:
                        if pnl >= 0:
                            total_gains += pnl
                        else:
                            total_losses += abs(pnl)

                        if stock_symbol == current_symbol:
                            if pnl >= 0:
                                current_stock_gains += pnl
                            else:
                                current_stock_losses += abs(pnl)

                        sell_count += 1

    net_gain = total_gains - total_losses
    taxable = max(0.0, net_gain - FREIBETRAG)
    tax_owed = taxable * TAX_RATE
    freibetrag_used = min(net_gain, FREIBETRAG) if net_gain > 0 else 0.0
    freibetrag_remaining = FREIBETRAG - freibetrag_used

    # How much more can you gain before hitting Freibetrag
    gain_until_taxed = max(0.0, FREIBETRAG - net_gain) if net_gain < FREIBETRAG else 0.0

    current_stock_net = current_stock_gains - current_stock_losses

    return {
        "year": current_year,
        "total_gains": round(total_gains, 2),
        "total_losses": round(total_losses, 2),
        "net_gain": round(net_gain, 2),
        "freibetrag": FREIBETRAG,
        "freibetrag_used": round(freibetrag_used, 2),
        "freibetrag_remaining": round(freibetrag_remaining, 2),
        "gain_until_taxed": round(gain_until_taxed, 2),
        "taxable": round(taxable, 2),
        "tax_rate_pct": round(TAX_RATE * 100, 3),
        "tax_owed": round(tax_owed, 2),
        "net_after_tax": round(net_gain - tax_owed, 2),
        "current_stock_gains": round(current_stock_gains, 2),
        "current_stock_losses": round(current_stock_losses, 2),
        "current_stock_net": round(current_stock_net, 2),
        "sell_count": sell_count,
    }


def compute_crypto_tax(user, current_symbol=None):
    """
    Compute German crypto tax analytics for the current year.

    German crypto tax rules:
    - Hold > 1 year → completely tax-free on sale
    - Hold < 1 year → subject to income tax (Einkommensteuer, rate varies)
    - Freigrenze: €1,000/year — if total short-term gains < €1,000, all tax-free
      (unlike Freibetrag: if you exceed €1,000, the ENTIRE amount is taxed)
    - Uses FIFO (First In, First Out) for determining holding period

    Returns a dict with tax breakdown and per-lot holding timers.
    """
    from datetime import date, timedelta
    from .models import CryptoAsset

    FREIGRENZE_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIGRENZE = FREIGRENZE_EUR * eur_usd  # threshold in USD for comparison
    current_year = date.today().year
    today = date.today()

    all_crypto_qs = CryptoAsset.objects.filter(user=user)
    crypto_ids = all_crypto_qs.values_list("crypto_id", flat=True).distinct()

    total_short_term_gains = 0.0
    total_short_term_losses = 0.0
    total_long_term_gains = 0.0
    current_crypto_short_gains = 0.0
    current_crypto_short_losses = 0.0

    # Per-lot timers for the current symbol
    holding_lots = []

    for crypto_id in crypto_ids:
        txs = (
            all_crypto_qs.filter(crypto_id=crypto_id)
            .select_related("crypto")
            .order_by("date", "status", "pk")
        )
        crypto_symbol = None
        # FIFO lot queue: list of {date, amount, price}
        lots = []

        for tx in txs:
            if crypto_symbol is None:
                crypto_symbol = tx.crypto.symbol
            amt = float(tx.amount)
            px = float(tx.price)

            if tx.status == "bought":
                lots.append({"date": tx.date, "amount": amt, "price": px})
            elif tx.status == "sold":
                remaining_to_sell = amt
                while remaining_to_sell > 0 and lots:
                    lot = lots[0]
                    sell_from_lot = min(remaining_to_sell, lot["amount"])
                    holding_days = (tx.date - lot["date"]).days
                    pnl = (px - lot["price"]) * sell_from_lot

                    if tx.date.year == current_year:
                        if holding_days <= 365:
                            # Short-term
                            if pnl >= 0:
                                total_short_term_gains += pnl
                            else:
                                total_short_term_losses += abs(pnl)
                            if crypto_symbol == current_symbol:
                                if pnl >= 0:
                                    current_crypto_short_gains += pnl
                                else:
                                    current_crypto_short_losses += abs(pnl)
                        else:
                            # Long-term → tax-free
                            total_long_term_gains += pnl if pnl > 0 else 0

                    lot["amount"] -= sell_from_lot
                    remaining_to_sell -= sell_from_lot
                    if lot["amount"] <= 0.0001:
                        lots.pop(0)

        # Collect remaining lots for current symbol's timer
        if crypto_symbol == current_symbol:
            for lot in lots:
                if lot["amount"] > 0.0001:
                    tax_free_date = lot["date"] + timedelta(days=366)
                    days_left = (tax_free_date - today).days
                    holding_lots.append(
                        {
                            "buy_date": lot["date"],
                            "amount": round(lot["amount"], 8),
                            "price": round(lot["price"], 2),
                            "tax_free_date": tax_free_date,
                            "days_left": max(days_left, 0),
                            "is_tax_free": days_left <= 0,
                        }
                    )

    net_short_term = total_short_term_gains - total_short_term_losses
    current_net = current_crypto_short_gains - current_crypto_short_losses

    # Freigrenze: if net short-term gains < 1000, all tax-free
    # If >= 1000, the ENTIRE amount is taxable (not just the excess)
    exceeds_freigrenze = net_short_term >= FREIGRENZE
    room_to_freigrenze = (
        max(0.0, FREIGRENZE - net_short_term) if not exceeds_freigrenze else 0.0
    )

    return {
        "year": current_year,
        "freigrenze": FREIGRENZE,
        "total_short_term_gains": round(total_short_term_gains, 2),
        "total_short_term_losses": round(total_short_term_losses, 2),
        "net_short_term": round(net_short_term, 2),
        "total_long_term_gains": round(total_long_term_gains, 2),
        "exceeds_freigrenze": exceeds_freigrenze,
        "room_to_freigrenze": round(room_to_freigrenze, 2),
        "current_crypto_short_gains": round(current_crypto_short_gains, 2),
        "current_crypto_short_losses": round(current_crypto_short_losses, 2),
        "current_crypto_net": round(current_net, 2),
        "holding_lots": holding_lots,
    }


def load_live_prices(model):
    """Load cached live prices and market caps for tracked symbols of a model."""
    result = []
    for symbol in model.objects.exclude(finnhub_symbol="").values_list(
        "symbol", flat=True
    ):
        price = cache.get(f"finnhub_{symbol}")
        mcap = cache.get(f"finnhub_{symbol}_mcap")
        result.append({"short": symbol, "price": price, "market_cap": mcap or 0})
    result.sort(key=lambda x: x["market_cap"], reverse=True)
    return result


def get_eur_usd_rate():
    """
    Get the current EUR → USD exchange rate.

    Caches the rate for 6 hours (ECB updates daily).
    Returns the rate as a float, e.g. 1.1372 means 1 EUR = 1.1372 USD.
    Returns None if the API is unreachable.
    """
    CACHE_KEY = "fx_eur_usd"
    rate = cache.get(CACHE_KEY)
    if rate is not None:
        return rate

    try:
        resp = requests.get(
            settings.FRANKFURTER_API_URL,
            params={"from": "EUR", "to": "USD"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("rates", {}).get("USD")
        if rate:
            cache.set(CACHE_KEY, float(rate), timeout=6 * 3600)
            logger.info("EUR/USD rate: %s", rate)
            return float(rate)
    except Exception as e:
        logger.warning("Failed to fetch EUR/USD rate: %s", e)

    return None


def cost_basis_for(txs):
    """Weighted-average cost basis for a queryset of buy/sell transactions."""
    cb = 0.0
    units = 0.0
    for tx in txs.order_by("date", "status", "pk"):
        amt = float(tx.amount)
        px = float(tx.price)
        if tx.status == "bought":
            cb += amt * px
            units += amt
        elif tx.status == "sold" and units > 0:
            avg = cb / units
            cb -= amt * avg
            units -= amt
    return round(cb, 2)


def sync_alert_cache():
    """Rebuild the Redis alert cache from the DB."""
    from .models import PriceAlert

    alerts = PriceAlert.objects.filter(email_sent=False).select_related(
        "stock", "crypto"
    )
    alert_data = {}
    for a in alerts:
        alert_data.setdefault(a.symbol, []).append(
            {
                "id": str(a.id),
                "user_id": str(a.user_id),
                "target_price": float(a.target_price),
                "direction": a.direction,
                "invest_amount": (
                    float(a.invest_amount) if a.invest_amount is not None else None
                ),
            }
        )
    cache.set("price_alerts_active", alert_data, timeout=None)
