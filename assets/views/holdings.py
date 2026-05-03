"""
Unified Holdings page — replaces the per-kind list views with a single
view that filters by ``?kind=stock|etf|crypto|all`` and surfaces ETFs
the user has a savings plan for even when there's no transaction yet.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render

from ..models import Instrument, Transaction
from ..services import cost_basis_for, get_asset_summary
from ._helpers import KIND_CHOICES


@login_required
def holdings_view(request):
    """Unified replacement for the per-kind list pages."""
    kind = request.GET.get("kind", "all")
    if kind not in {"all", "stock", "etf", "crypto"}:
        kind = "all"

    base_qs = Transaction.objects.filter(user=request.user)
    if kind != "all":
        base_qs = base_qs.filter(instrument__kind=kind)

    summary = list(get_asset_summary(base_qs))

    enriched = []
    allocation = []
    pnl_ranking = []
    seen_symbols = set()

    for row in summary:
        symbol = row["symbol"]
        seen_symbols.add(symbol)
        price = cache.get(f"finnhub_{symbol}")
        amt = float(row["total"])
        worth = round(amt * float(price), 2) if price is not None and amt > 0 else None
        enriched.append({
            **row,
            "price": price,
            "worth": worth,
        })
        if price is not None and amt > 0:
            allocation.append({
                "label": row["name"],
                "symbol": symbol,
                "value": worth or 0,
            })
            cb = cost_basis_for(base_qs.filter(instrument__symbol=symbol))
            value = worth or 0
            pnl = round(value - cb, 2)
            pnl_pct = round((pnl / cb) * 100, 2) if cb > 0 else 0.0
            pnl_ranking.append({
                "label": row["name"],
                "symbol": symbol,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            })

    pnl_ranking.sort(key=lambda r: r["pnl_pct"], reverse=True)

    # ETFs the user has a savings plan for but no transactions yet.
    if kind in ("all", "etf"):
        plan_etfs = Instrument.objects.filter(
            kind="etf", savings_plans__user=request.user
        ).distinct()
        for etf in plan_etfs:
            if etf.symbol in seen_symbols:
                continue
            enriched.append({
                "name": etf.name,
                "symbol": etf.symbol,
                "kind": "etf",
                "total": 0.0,
                "price": cache.get(f"finnhub_{etf.symbol}"),
                "worth": None,
            })

    return render(request, "assets/holdings.html", {
        "rows": enriched,
        "allocation_json": json.dumps(allocation),
        "pnl_ranking": pnl_ranking,
        "current_kind": kind,
        "kind_choices": KIND_CHOICES,
    })
