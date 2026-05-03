import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, F, FloatField, Max, Min, Sum, Value, When
from django.db.models.functions import Coalesce

logger = logging.getLogger(__name__)

ALLOWED_PER_PAGE = [20, 40]
DEFAULT_PER_PAGE = 20
DETAIL_SORT_FIELDS = ["date", "price", "amount", "fee", "status"]
DETAIL_COLUMNS = [
    ("date", "Date"),
    ("price", "Price ($)"),
    ("amount", "Amount"),
    ("fee", "Fee ($)"),
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


def get_asset_summary(queryset):
    """
    Group a Transaction queryset by instrument and return rows with name,
    symbol, kind, and net total amount (bought=+, sold=−).
    """
    return (
        queryset.values(
            name=F("instrument__name"),
            symbol=F("instrument__symbol"),
            kind=F("instrument__kind"),
        )
        .annotate(
            total=Coalesce(
                Sum(
                    Case(
                        When(status="bought", then=F("amount")),
                        When(status="sold", then=F("amount") * Value(Decimal("-1.0"))),
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

    Uses weighted-average cost basis: buys increase cost basis (price × amount
    + buy fee), sells reduce units but do NOT change the average (cost basis
    reduced proportionally). Sell fees come off the realized proceeds.

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
        fee = float(tx.fee or 0)

        if tx.status == "bought":
            cost_basis += amt * px + fee
            units += amt
            total_invested += amt * px + fee
        elif tx.status == "sold":
            if units > 0:
                avg = cost_basis / units
                cost_basis -= amt * avg
                units -= amt
            total_sold_value += amt * px - fee
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

        analytics["sell_5"] = round(avg_price * 1.05, 2)
        analytics["sell_10"] = round(avg_price * 1.10, 2)
        analytics["sell_25"] = round(avg_price * 1.25, 2)

        target_avg = avg_price * 0.90
        buy_price_for_minus_10 = (target_avg * (units * 2) - cost_basis) / units
        analytics["buy_avg_minus_10"] = (
            round(buy_price_for_minus_10, 2) if buy_price_for_minus_10 > 0 else 0.0
        )
        analytics["buy_avg_minus_10_spend"] = (
            round(buy_price_for_minus_10 * units, 2)
            if buy_price_for_minus_10 > 0
            else 0.0
        )

    return analytics


def _compute_freibetrag_tax(user, kind, current_symbol, key_prefix):
    """
    Shared weighted-average tax calculator for stocks and ETFs.

    German rules: 26.375% on gains above €1,000 Freibetrag.
    Losses can only offset gains within the same kind.
    """
    from datetime import date

    from .models import Transaction

    TAX_RATE = 0.26375
    FREIBETRAG_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIBETRAG = FREIBETRAG_EUR * eur_usd
    current_year = date.today().year

    qs = Transaction.objects.filter(user=user, instrument__kind=kind)
    # Strip default ordering before DISTINCT — Transaction.Meta.ordering leaks
    # into the SELECT and yields duplicate instrument_ids, double-counting
    # gains for any user who has more than one transaction per instrument.
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    total_gains = 0.0
    total_losses = 0.0
    current_gains = 0.0
    current_losses = 0.0
    sell_count = 0

    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        cost_basis = 0.0
        units = 0.0

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                cost_basis += amt * px + fee
                units += amt
            elif tx.status == "sold" and units > 0:
                avg = cost_basis / units
                pnl = (px - avg) * amt - fee
                cost_basis -= amt * avg
                units -= amt

                if tx.date.year == current_year:
                    if pnl >= 0:
                        total_gains += pnl
                    else:
                        total_losses += abs(pnl)

                    if symbol == current_symbol:
                        if pnl >= 0:
                            current_gains += pnl
                        else:
                            current_losses += abs(pnl)

                    sell_count += 1

    net_gain = total_gains - total_losses
    taxable = max(0.0, net_gain - FREIBETRAG)
    tax_owed = taxable * TAX_RATE
    freibetrag_used = min(net_gain, FREIBETRAG) if net_gain > 0 else 0.0
    freibetrag_remaining = FREIBETRAG - freibetrag_used
    gain_until_taxed = max(0.0, FREIBETRAG - net_gain) if net_gain < FREIBETRAG else 0.0
    current_net = current_gains - current_losses

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
        f"current_{key_prefix}_gains": round(current_gains, 2),
        f"current_{key_prefix}_losses": round(current_losses, 2),
        f"current_{key_prefix}_net": round(current_net, 2),
        "sell_count": sell_count,
    }


def compute_stock_tax(user, current_symbol=None):
    """German stock capital-gains tax for the current year (Freibetrag €1,000)."""
    return _compute_freibetrag_tax(user, "stock", current_symbol, "stock")


def compute_etf_tax(user, current_symbol=None):
    """German ETF capital-gains tax for the current year (Freibetrag €1,000)."""
    return _compute_freibetrag_tax(user, "etf", current_symbol, "etf")


def compute_crypto_tax(user, current_symbol=None):
    """
    Compute German crypto tax analytics for the current year.

    German crypto tax rules:
    - Hold > 1 year → completely tax-free on sale
    - Hold < 1 year → subject to income tax (Einkommensteuer)
    - Freigrenze: €1,000/year — if total short-term gains < €1,000, all tax-free
      (unlike Freibetrag: if you exceed €1,000, the ENTIRE amount is taxed)
    - Uses FIFO (First In, First Out) for determining holding period
    """
    from datetime import date, timedelta

    from .models import Transaction

    FREIGRENZE_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIGRENZE = FREIGRENZE_EUR * eur_usd
    current_year = date.today().year
    today = date.today()

    qs = Transaction.objects.filter(user=user, instrument__kind="crypto")
    # See _compute_freibetrag_tax for why .order_by() is needed before .distinct().
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    total_short_term_gains = 0.0
    total_short_term_losses = 0.0
    total_long_term_gains = 0.0
    current_short_gains = 0.0
    current_short_losses = 0.0
    holding_lots = []

    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        lots = []

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                # Bake buy fee into the lot's per-unit price so cost basis
                # for FIFO remains correct without tracking fee separately.
                effective_price = px + (fee / amt if amt > 0 else 0)
                lots.append({"date": tx.date, "amount": amt, "price": effective_price})
            elif tx.status == "sold":
                # Allocate the sell fee proportionally across consumed lots.
                # `fee_per_unit` is the slice of this sell's fee borne by
                # each unit consumed below.
                fee_per_unit = (fee / amt) if amt > 0 else 0
                remaining_to_sell = amt
                while remaining_to_sell > 0 and lots:
                    lot = lots[0]
                    sell_from_lot = min(remaining_to_sell, lot["amount"])
                    holding_days = (tx.date - lot["date"]).days
                    pnl = (px - lot["price"]) * sell_from_lot - fee_per_unit * sell_from_lot

                    if tx.date.year == current_year:
                        if holding_days <= 365:
                            if pnl >= 0:
                                total_short_term_gains += pnl
                            else:
                                total_short_term_losses += abs(pnl)
                            if symbol == current_symbol:
                                if pnl >= 0:
                                    current_short_gains += pnl
                                else:
                                    current_short_losses += abs(pnl)
                        else:
                            total_long_term_gains += pnl if pnl > 0 else 0

                    lot["amount"] -= sell_from_lot
                    remaining_to_sell -= sell_from_lot
                    if lot["amount"] <= 0.0001:
                        lots.pop(0)

        if symbol == current_symbol:
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
    current_net = current_short_gains - current_short_losses
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
        "current_crypto_short_gains": round(current_short_gains, 2),
        "current_crypto_short_losses": round(current_short_losses, 2),
        "current_crypto_net": round(current_net, 2),
        "holding_lots": holding_lots,
    }


def load_live_prices(kind, watchlist_ids=None):
    """
    Load cached live prices and market caps for tracked symbols of a kind.

    `watchlist_ids` (a set of UUIDs) lets the Market page mark each row as
    already watched.
    """
    from .models import Instrument

    if watchlist_ids is None:
        watchlist_ids = set()

    result = []
    for inst in Instrument.objects.filter(kind=kind).exclude(finnhub_symbol=""):
        price = cache.get(f"finnhub_{inst.symbol}")
        mcap = cache.get(f"finnhub_{inst.symbol}_mcap")
        result.append({
            "id": str(inst.id),
            "short": inst.symbol,
            "price": price,
            "market_cap": mcap or 0,
            "watching": inst.id in watchlist_ids,
        })
    result.sort(key=lambda x: x["market_cap"], reverse=True)
    return result


def get_eur_usd_rate():
    """
    Get the current EUR → USD exchange rate.

    Caches the rate for 6 hours (ECB updates daily).
    Returns None if the API is unreachable.
    """
    CACHE_KEY = "fx_eur_usd"
    UNAVAILABLE_KEY = "fx_eur_usd_unavailable"
    rate = cache.get(CACHE_KEY)
    if rate is not None:
        return rate

    if cache.get(UNAVAILABLE_KEY):
        return None

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
            cache.delete(UNAVAILABLE_KEY)
            logger.info("EUR/USD rate: %s", rate)
            return float(rate)
    except Exception as e:
        logger.warning("Failed to fetch EUR/USD rate: %s", e)

    cache.set(UNAVAILABLE_KEY, True, timeout=15 * 60)
    return None


def cost_basis_for(txs):
    """
    Weighted-average remaining cost basis for a queryset of buy/sell
    transactions. Buy fees increase the basis; sell fees do not (they hit
    realized P&L instead, not the basis of remaining units).
    """
    cb = 0.0
    units = 0.0
    for tx in txs.order_by("date", "status", "pk"):
        amt = float(tx.amount)
        px = float(tx.price)
        fee = float(tx.fee or 0)
        if tx.status == "bought":
            cb += amt * px + fee
            units += amt
        elif tx.status == "sold" and units > 0:
            avg = cb / units
            cb -= amt * avg
            units -= amt
    return round(cb, 2)


def advance_savings_plan_date(plan, current):
    """
    Compute the next execution date for a savings plan after `current`.

    Monthly/quarterly anchor to the original `start_date.day`, clamped to
    month-end (so a 31st plan falls on Feb 28/29, March 31, April 30, etc.).
    """
    import calendar
    from datetime import date, timedelta

    interval = plan.interval
    if interval == "weekly":
        return current + timedelta(days=7)
    if interval == "biweekly":
        return current + timedelta(days=14)

    months = {"monthly": 1, "quarterly": 3}.get(interval, 1)
    target_year = current.year + (current.month - 1 + months) // 12
    target_month = (current.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    target_day = min(plan.start_date.day, last_day)
    return date(target_year, target_month, target_day)


def execute_due_savings_plans():
    """
    Run all active ETFSavingsPlans whose next_execution_date <= today.

    For each due plan:
      - Loop while still due (catches up missed days).
      - Use the ETF's last_price (which mirrors the price cache).
        If unavailable, create the transaction with price=0 and amount=0
        so the user can fill it in manually later.
      - Insert a Transaction row dated `next_execution_date`.
      - Advance next_execution_date by interval, anchored to start_date.day.

    Idempotent: safe to call repeatedly; each plan only executes when due.
    """
    from datetime import date

    from django.utils import timezone

    from .models import ETFSavingsPlan, Transaction

    today = date.today()
    due = ETFSavingsPlan.objects.filter(
        active=True, next_execution_date__lte=today
    ).select_related("instrument", "user")

    executed = 0
    for plan in due:
        while plan.active and plan.next_execution_date <= today:
            if plan.currency == "EUR":
                fx = get_eur_usd_rate()
                if fx is None:
                    logger.warning(
                        "Skipping EUR savings plan %s: EUR/USD rate unavailable",
                        plan.id,
                    )
                    break
                usd_spend = float(plan.amount) * fx
            else:
                usd_spend = float(plan.amount)

            last_price = plan.instrument.last_price
            if last_price is not None and float(last_price) > 0:
                price_val = float(last_price)
                amount_val = usd_spend / price_val
            else:
                price_val = 0.0
                amount_val = 0.0

            Transaction.objects.create(
                user=plan.user,
                instrument=plan.instrument,
                price=Decimal(str(round(price_val, 2))),
                amount=Decimal(str(round(amount_val, 8))),
                date=plan.next_execution_date,
                status="bought",
            )

            plan.last_executed_at = timezone.now()
            plan.next_execution_date = advance_savings_plan_date(
                plan, plan.next_execution_date
            )
            plan.save(update_fields=["last_executed_at", "next_execution_date"])
            executed += 1

    if executed:
        logger.info("Executed %d ETF savings plan transaction(s)", executed)
    return executed


def get_cash_summary(user):
    """
    Return totals for a user's cash deposits/withdrawals (all USD).

    `net_invested_usd` is the principal still committed to the brokerage:
    deposits − withdrawals.
    """
    from .models import CashFlow

    flows = CashFlow.objects.filter(user=user)
    deposits = float(
        flows.filter(direction="deposit").aggregate(s=Sum("amount_usd"))["s"] or 0
    )
    withdrawals = float(
        flows.filter(direction="withdraw").aggregate(s=Sum("amount_usd"))["s"] or 0
    )
    return {
        "deposits_usd": round(deposits, 2),
        "withdrawals_usd": round(withdrawals, 2),
        "net_invested_usd": round(deposits - withdrawals, 2),
    }


def get_total_portfolio_worth_usd(user):
    """
    Sum the user's current holdings (all kinds) in USD using the price cache.
    """
    from .models import Transaction

    total = 0.0
    for row in get_asset_summary(Transaction.objects.filter(user=user)):
        amt = float(row["total"])
        if amt <= 0:
            continue
        price = cache.get(f"finnhub_{row['symbol']}")
        if price is None:
            continue
        total += amt * float(price)
    return round(total, 2)


def sync_alert_cache():
    """Rebuild the Redis alert cache from the DB."""
    from .models import PriceAlert

    alerts = PriceAlert.objects.filter(email_sent=False).select_related("instrument")
    alert_data = {}
    for a in alerts:
        if a.instrument_id is None:
            continue
        alert_data.setdefault(a.instrument.symbol, []).append(
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


def snapshot_today_from_cache(instrument):
    """
    Persist today's price for an instrument from the live cache, if today
    isn't already snapshotted. Returns the PriceSnapshot or None.
    """
    from datetime import date as dt_date
    from decimal import Decimal

    from .models import PriceSnapshot

    today = dt_date.today()
    if PriceSnapshot.objects.filter(instrument=instrument, date=today).exists():
        return None

    if instrument.kind == "etf":
        # ETFs use last_price (which is the cache mirror anyway).
        if instrument.last_price is None:
            return None
        price = instrument.last_price
        source = PriceSnapshot.Source.MANUAL
    else:
        live = cache.get(f"finnhub_{instrument.symbol}")
        if live is None:
            return None
        price = Decimal(str(live))
        source = PriceSnapshot.Source.CACHE

    return PriceSnapshot.objects.create(
        instrument=instrument,
        date=today,
        price=price,
        source=source,
    )


def _coingecko_id_for(symbol):
    """Best-effort symbol → CoinGecko coin id lookup, with cache."""
    cache_key = f"cg_id_{symbol.upper()}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    try:
        resp = requests.get(
            settings.COINGECKO_MARKETS_URL,
            params={"vs_currency": "usd", "symbols": symbol.lower(), "per_page": 5, "page": 1},
            timeout=10,
        )
        resp.raise_for_status()
        for coin in resp.json():
            if (coin.get("symbol") or "").upper() == symbol.upper():
                cache.set(cache_key, coin["id"], timeout=24 * 3600)
                return coin["id"]
    except Exception as e:
        logger.warning("CoinGecko id lookup failed for %s: %s", symbol, e)
    return None


def backfill_finnhub_stock_candles(instrument, days=365):
    """
    Pull daily OHLC from Finnhub for a stock instrument and write
    PriceSnapshot rows. Returns count written.

    Finnhub free tier may reject /stock/candle; we log and skip on 4xx.
    """
    import time
    from datetime import date as dt_date, timedelta
    from decimal import Decimal

    from .models import PriceSnapshot

    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        return 0

    end = dt_date.today()
    start = end - timedelta(days=days)
    try:
        resp = requests.get(
            f"{settings.FINNHUB_REST_URL}/stock/candle",
            params={
                "symbol": instrument.finnhub_symbol or instrument.symbol,
                "resolution": "D",
                "from": int(time.mktime(start.timetuple())),
                "to": int(time.mktime(end.timetuple())),
                "token": api_key,
            },
            timeout=20,
        )
        if resp.status_code == 403 or resp.status_code == 401:
            logger.warning(
                "Finnhub /stock/candle denied for %s (likely free-tier limitation)",
                instrument.symbol,
            )
            return 0
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Finnhub candle fetch failed for %s: %s", instrument.symbol, e)
        return 0

    if data.get("s") != "ok":
        return 0

    closes = data.get("c", [])
    timestamps = data.get("t", [])
    if len(closes) != len(timestamps):
        return 0

    written = 0
    for ts, close in zip(timestamps, closes):
        d = dt_date.fromtimestamp(ts)
        try:
            _, created = PriceSnapshot.objects.update_or_create(
                instrument=instrument,
                date=d,
                defaults={
                    "price": Decimal(str(close)),
                    "source": PriceSnapshot.Source.FINNHUB,
                },
            )
            if created:
                written += 1
        except Exception as e:
            logger.warning("Snapshot write failed for %s @ %s: %s", instrument.symbol, d, e)
    return written


def backfill_coingecko_crypto(instrument, days=365):
    """
    Pull daily prices from CoinGecko for a crypto instrument. Returns count
    written. Free tier supports up to 365 days.
    """
    from datetime import date as dt_date, datetime, timezone as dt_tz
    from decimal import Decimal

    from .models import PriceSnapshot

    coin_id = _coingecko_id_for(instrument.symbol)
    if not coin_id:
        return 0

    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": min(days, 365), "interval": "daily"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("CoinGecko chart fetch failed for %s: %s", instrument.symbol, e)
        return 0

    written = 0
    seen_dates = set()
    for ts_ms, price in data.get("prices", []):
        d = datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc).date()
        if d in seen_dates:
            continue
        seen_dates.add(d)
        try:
            _, created = PriceSnapshot.objects.update_or_create(
                instrument=instrument,
                date=d,
                defaults={
                    "price": Decimal(str(price)),
                    "source": PriceSnapshot.Source.COINGECKO,
                },
            )
            if created:
                written += 1
        except Exception as e:
            logger.warning("Snapshot write failed for %s @ %s: %s", instrument.symbol, d, e)
    return written


def run_price_snapshot_catchup(backfill_days=30, throttle_seconds=6):
    """
    Idempotent catchup task. For every instrument, ensure today is
    snapshotted. If recent days are missing (PC was off), try to backfill
    from the appropriate API.

    `throttle_seconds` controls the pause between API calls so we don't
    trip CoinGecko's free-tier rate limit (~10-30 req/min).

    Called periodically from the Celery price-stream worker so a missed
    midnight gets caught up the next time the machine is alive.
    """
    import time
    from datetime import date as dt_date, timedelta

    from .models import Instrument, PriceSnapshot

    today = dt_date.today()
    written = 0
    api_calls = 0  # how many backfill API requests we've issued

    for inst in Instrument.objects.all():
        # 1. Today's snapshot from cache (no network).
        snap = snapshot_today_from_cache(inst)
        if snap:
            written += 1

        # 2. Backfill any historical gap. Skip ETFs (no API source).
        if inst.kind == "etf":
            continue

        latest = (
            PriceSnapshot.objects.filter(instrument=inst, date__lt=today)
            .order_by("-date")
            .first()
        )
        oldest_needed = today - timedelta(days=backfill_days)
        gap_start = (latest.date + timedelta(days=1)) if latest else oldest_needed
        if gap_start > today - timedelta(days=1):
            continue

        gap_days = (today - gap_start).days
        if gap_days <= 0:
            continue

        if api_calls > 0:
            time.sleep(throttle_seconds)

        if inst.kind == "stock":
            written += backfill_finnhub_stock_candles(inst, days=min(gap_days + 5, 365))
        elif inst.kind == "crypto":
            written += backfill_coingecko_crypto(inst, days=min(gap_days + 5, 365))
        api_calls += 1

    if written:
        logger.info("Price snapshot catchup wrote %d rows", written)
    return written


def get_portfolio_history(user):
    """
    Portfolio worth and net invested over time, at daily resolution.

    Returns ``{"points": [...], "fallback_days": int}`` so the caller
    knows how many days had to fall back to last-transaction-price (i.e.
    weren't covered by a PriceSnapshot for at least one held instrument).
    When ``fallback_days == 0`` the chart is fully DB-backed.

    Strategy:
      - Walk every day from the first event to today (inclusive).
      - On each day, advance holdings + net-invested as cash flows and
        transactions occur.
      - For each held instrument with positive quantity, look up the
        day's PriceSnapshot; fall back to the most recent known price
        for that instrument (transactions or earlier snapshots) if
        missing. A day is counted as "fallback" if any held symbol on
        that day had no snapshot for that exact date.
    """
    from datetime import date as dt_date, timedelta

    from .models import CashFlow, PriceSnapshot, Transaction

    cash_flows = list(CashFlow.objects.filter(user=user).order_by("date", "created_at"))
    txs = list(
        Transaction.objects.filter(user=user)
        .select_related("instrument")
        .order_by("date", "created_at", "pk")
    )
    if not cash_flows and not txs:
        return {"points": [], "fallback_days": 0}

    first_event = min(
        ([c.date for c in cash_flows] or [dt_date.today()])
        + ([t.date for t in txs] or [dt_date.today()])
    )
    today = dt_date.today()

    # Pre-fetch all snapshots for the period, indexed by (symbol, date).
    held_symbols = {t.instrument.symbol for t in txs}
    snapshot_map = {}
    if held_symbols:
        snaps = PriceSnapshot.objects.filter(
            instrument__symbol__in=held_symbols,
            date__gte=first_event,
            date__lte=today,
        ).values_list("instrument__symbol", "date", "price")
        for sym, d, p in snaps:
            snapshot_map[(sym, d)] = float(p)

    cumulative_cash = 0.0
    holdings = {}
    last_price = {}  # rolling fallback per symbol
    cash_idx = 0
    tx_idx = 0
    points = []
    fallback_days = 0

    d = first_event
    while d <= today:
        # Apply events landing on or before this date.
        while cash_idx < len(cash_flows) and cash_flows[cash_idx].date <= d:
            c = cash_flows[cash_idx]
            cumulative_cash += float(c.amount_usd) * (
                1 if c.direction == "deposit" else -1
            )
            cash_idx += 1
        while tx_idx < len(txs) and txs[tx_idx].date <= d:
            t = txs[tx_idx]
            sym = t.instrument.symbol
            amt = float(t.amount)
            holdings[sym] = holdings.get(sym, 0.0) + (
                amt if t.status == "bought" else -amt
            )
            last_price[sym] = float(t.price)
            tx_idx += 1

        # Roll any snapshots into last_price so subsequent gaps still
        # benefit from the most recent known price.
        for sym in list(holdings.keys()):
            snap = snapshot_map.get((sym, d))
            if snap is not None:
                last_price[sym] = snap

        # Compute estimated worth + flag fallback usage on this day.
        est = 0.0
        used_fallback_today = False
        for sym, qty in holdings.items():
            if qty <= 0:
                continue
            snap = snapshot_map.get((sym, d))
            if snap is not None:
                est += qty * snap
            else:
                price = last_price.get(sym)
                if price is None:
                    continue
                est += qty * price
                used_fallback_today = True

        if used_fallback_today:
            fallback_days += 1

        points.append({
            "date": d.isoformat(),
            "net_invested": round(cumulative_cash, 2),
            "est_worth": round(est, 2),
        })

        d += timedelta(days=1)

    # Today: if no snapshot landed yet, use the live cache as the
    # closest-to-realtime value.
    if points and points[-1]["date"] == today.isoformat():
        snap_today_full = all(
            snapshot_map.get((sym, today)) is not None
            for sym, qty in holdings.items()
            if qty > 0
        )
        if not snap_today_full:
            est_now = 0.0
            for sym, qty in holdings.items():
                if qty <= 0:
                    continue
                p = (
                    snapshot_map.get((sym, today))
                    or cache.get(f"finnhub_{sym}")
                    or last_price.get(sym)
                    or 0
                )
                est_now += qty * float(p)
            points[-1]["est_worth"] = round(est_now, 2)

    return {"points": points, "fallback_days": fallback_days}


def lookup_instrument(kind, symbol):
    """
    Probe Finnhub (and CoinGecko for crypto names) to verify that a symbol
    exists and resolve its canonical name + current price.

    Returns one of:
      {"valid": True, "name": str, "symbol": str, "finnhub_symbol": str,
       "current_price": float}
      {"valid": False, "error": str}

    Stocks: `/stock/profile2` + `/quote`. Both must return data.
    Crypto: scoped to Binance USDT pairs (matches existing `BINANCE:XYZUSDT`
    convention). Finnhub `/quote?symbol=BINANCE:{X}USDT` for the price;
    CoinGecko `/coins/markets` for the human-readable name.
    """
    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        return {"valid": False, "error": "FINNHUB_API_KEY not configured."}

    symbol = symbol.strip().upper()
    if not symbol:
        return {"valid": False, "error": "Symbol is required."}

    if kind == "stock":
        try:
            profile = requests.get(
                f"{settings.FINNHUB_REST_URL}/stock/profile2",
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            profile.raise_for_status()
            pdata = profile.json()
        except Exception as e:
            logger.warning("Finnhub profile lookup failed for %s: %s", symbol, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        name = pdata.get("name")
        if not name:
            return {
                "valid": False,
                "error": f"'{symbol}' not found on Finnhub. Check the ticker.",
            }

        try:
            quote = requests.get(
                f"{settings.FINNHUB_REST_URL}/quote",
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            quote.raise_for_status()
            qdata = quote.json()
        except Exception as e:
            logger.warning("Finnhub quote lookup failed for %s: %s", symbol, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        price = qdata.get("c")
        if not price or price <= 0:
            return {
                "valid": False,
                "error": f"Finnhub has no live price for '{symbol}'.",
            }

        return {
            "valid": True,
            "name": name,
            "symbol": symbol,
            "finnhub_symbol": symbol,
            "current_price": float(price),
        }

    if kind == "crypto":
        finnhub_sym = f"BINANCE:{symbol}USDT"
        try:
            quote = requests.get(
                f"{settings.FINNHUB_REST_URL}/quote",
                params={"symbol": finnhub_sym, "token": api_key},
                timeout=10,
            )
            quote.raise_for_status()
            qdata = quote.json()
        except Exception as e:
            logger.warning("Finnhub crypto quote failed for %s: %s", finnhub_sym, e)
            return {"valid": False, "error": "Couldn't reach Finnhub. Try again."}

        price = qdata.get("c")
        if not price or price <= 0:
            return {
                "valid": False,
                "error": (
                    f"'{symbol}' not found as a Binance USDT pair on Finnhub."
                ),
            }

        # Resolve canonical name from CoinGecko (best-effort).
        name = symbol
        try:
            cg = requests.get(
                settings.COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "symbols": symbol.lower(),
                    "per_page": 5,
                    "page": 1,
                },
                timeout=10,
            )
            cg.raise_for_status()
            for coin in cg.json():
                if (coin.get("symbol") or "").upper() == symbol:
                    name = coin.get("name") or symbol
                    break
        except Exception as e:
            logger.warning("CoinGecko name lookup failed for %s: %s", symbol, e)

        return {
            "valid": True,
            "name": name,
            "symbol": symbol,
            "finnhub_symbol": finnhub_sym,
            "current_price": float(price),
        }

    return {"valid": False, "error": f"Unsupported kind '{kind}'."}


def refresh_instrument_last_price(instrument):
    """
    Mirror the most recent transaction's price onto the master Instrument.

    Picks the latest by (date, pk) across all users so historical inserts/edits
    don't clobber a more recent price. Used after creating/editing ETF
    transactions where `last_price` drives savings-plan execution.
    """
    latest = instrument.transactions.order_by("-date", "-pk").first()
    new_price = latest.price if latest else None
    if new_price != instrument.last_price:
        instrument.last_price = new_price
        instrument.save(update_fields=["last_price"])
