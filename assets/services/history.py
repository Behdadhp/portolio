"""
Daily-resolution portfolio history reconstruction. Walks every day from
the user's first event to today, advancing holdings + net invested,
pricing each held instrument from PriceSnapshot rows (with rolling
last-known-price fallback), and falling back to the live cache for
today.
"""

from django.core.cache import cache


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

    from ..models import CashFlow, PriceSnapshot, Transaction

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
