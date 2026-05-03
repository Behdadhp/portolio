"""
Private helpers shared across multiple view modules.

* ``_list_view`` / ``_detail_view`` / ``_add_view`` / ``_edit_view`` /
  ``_delete_view`` — the generic per-kind CRUD scaffolding consumed by
  ``stock``, ``etf``, and ``crypto`` view modules.
* ``_instrument_create_view`` — shared master-record creation flow used
  by both ``stock_create_view`` and ``crypto_create_view`` (Finnhub
  re-verification on POST).
* ``KIND_CHOICES`` — kind dropdown options used by the Holdings and
  Transactions pages.
* ``_parse_iso_date`` / ``_querystring_for`` — small Reports helpers.
"""

import json
from datetime import datetime

from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Instrument, PriceAlert, Transaction
from ..services import (
    DETAIL_COLUMNS,
    apply_filters,
    compute_analytics,
    cost_basis_for,
    get_asset_summary,
    get_eur_usd_rate,
    get_filter_ranges,
    lookup_instrument,
    sort_and_paginate,
)


KIND_CHOICES = [
    ("all", "All"),
    ("stock", "Stocks"),
    ("etf", "ETFs"),
    ("crypto", "Crypto"),
]


# ── Generic CRUD helpers ─────────────────────────────────────


def _list_view(request, kind, template, context_key, extra_rows=None):
    base_qs = Transaction.objects.filter(user=request.user, instrument__kind=kind)
    summary = get_asset_summary(base_qs)
    enriched = []
    allocation = []
    pnl_ranking = []
    for row in summary:
        price = cache.get(f"finnhub_{row['symbol']}")
        row["price"] = price
        amt = float(row["total"])
        row["worth"] = round(amt * float(price), 2) if price is not None else None
        enriched.append(row)
        worth = round(amt * float(price), 2) if price is not None and amt > 0 else 0
        allocation.append(
            {"label": row["name"], "symbol": row["symbol"], "value": worth}
        )
        if price is not None and amt > 0:
            cb = cost_basis_for(
                base_qs.filter(instrument__symbol=row["symbol"])
            )
            value = round(amt * float(price), 2)
            pnl = round(value - cb, 2)
            pnl_pct = round((pnl / cb) * 100, 2) if cb > 0 else 0.0
            pnl_ranking.append(
                {
                    "label": row["name"],
                    "symbol": row["symbol"],
                    "value": value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                }
            )

    pnl_ranking.sort(key=lambda r: r["pnl_pct"], reverse=True)

    if extra_rows:
        seen = {row["symbol"] for row in enriched}
        for row in extra_rows:
            if row["symbol"] not in seen:
                enriched.append(row)

    return render(
        request,
        template,
        {
            context_key: enriched,
            "allocation_json": json.dumps(allocation),
            "pnl_ranking": pnl_ranking,
        },
    )


def _detail_view(request, symbol, kind, context_key, template, extra_context=None):
    instrument = get_object_or_404(Instrument, kind=kind, symbol=symbol)
    base_qs = Transaction.objects.filter(user=request.user, instrument=instrument)

    summary = get_asset_summary(base_qs).first()
    total = summary["total"] if summary else 0

    analytics = compute_analytics(base_qs, symbol)

    ranges = get_filter_ranges(base_qs)
    transactions, filters = apply_filters(request, base_qs.order_by("-date"))
    page_obj, current_sort, current_order, per_page = sort_and_paginate(
        request, transactions
    )

    active_alerts = PriceAlert.objects.filter(
        user=request.user, instrument=instrument
    ).select_related("instrument")

    context = {
        "page_obj": page_obj,
        context_key: instrument,
        "total": total,
        "analytics": analytics,
        "asset_symbol": symbol,
        "current_sort": current_sort,
        "current_order": current_order,
        "per_page": per_page,
        "filters": filters,
        "columns": DETAIL_COLUMNS,
        "eur_usd_rate": get_eur_usd_rate(),
        "active_alerts": active_alerts,
        **ranges,
    }
    if extra_context:
        context.update(extra_context)
    return render(request, template, context)


def _add_view(request, form_class, kind, context_key, template, detail_url, symbol=None):
    initial = {}
    instrument = None
    if symbol:
        instrument = get_object_or_404(Instrument, kind=kind, symbol=symbol)
        initial[context_key] = instrument

    form = form_class(initial=initial)

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.user = request.user
            tx.save()
            return redirect(detail_url, symbol=tx.instrument.symbol)

    return render(
        request,
        template,
        {
            "form": form,
            context_key: instrument,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


def _edit_view(request, pk, form_class, kind, context_key, template, detail_url):
    tx = get_object_or_404(
        Transaction, pk=pk, user=request.user, instrument__kind=kind
    )
    form = form_class(instance=tx)

    if request.method == "POST":
        form = form_class(request.POST, instance=tx)
        if form.is_valid():
            form.save()
            return redirect(detail_url, symbol=tx.instrument.symbol)

    return render(
        request,
        template,
        {
            "form": form,
            "transaction": tx,
            context_key: tx.instrument,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


def _delete_view(request, pk, kind, context_key, template, list_url, detail_url):
    tx = get_object_or_404(
        Transaction, pk=pk, user=request.user, instrument__kind=kind
    )
    instrument = tx.instrument

    if request.method == "POST":
        tx.delete()
        if not Transaction.objects.filter(
            user=request.user, instrument=instrument
        ).exists():
            return redirect(list_url)
        return redirect(detail_url, symbol=instrument.symbol)

    return render(request, template, {"transaction": tx, context_key: instrument})


# ── Master-record create flow shared by stock and crypto ───


def _instrument_create_view(request, kind, form_class, list_route, detail_route, title):
    """
    Shared create flow for Stock and Crypto masters. Re-verifies the symbol
    against Finnhub on POST as defense-in-depth (the JS verify step in the
    UI is the primary check).
    """
    initial = {}
    prefill_symbol = request.GET.get("symbol", "").strip().upper()
    if prefill_symbol:
        initial["symbol"] = prefill_symbol
    form = form_class(initial=initial)
    error = None

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            symbol = form.cleaned_data["symbol"].strip().upper()

            if Instrument.objects.filter(kind=kind, symbol=symbol).exists():
                error = f"'{symbol}' is already in your portfolio."
            else:
                result = lookup_instrument(kind, symbol)
                if not result["valid"]:
                    error = result["error"]
                else:
                    instrument = Instrument.objects.create(
                        kind=kind,
                        name=result["name"],
                        symbol=result["symbol"],
                        finnhub_symbol=result["finnhub_symbol"],
                    )
                    # Prime the price cache so the UI doesn't show "—" until
                    # the next WS tick (which may not arrive for a while).
                    cache.set(
                        f"finnhub_{instrument.symbol}",
                        result["current_price"],
                        timeout=None,
                    )
                    return redirect(detail_route, symbol=instrument.symbol)

    return render(
        request,
        "assets/instrument_master_form.html",
        {
            "form": form,
            "kind": kind,
            "title": title,
            "list_route": list_route,
            "error": error,
        },
    )


# ── Reports parsing helpers ──────────────────────────────


def _parse_iso_date(s):
    """Best-effort YYYY-MM-DD parse, returning None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _querystring_for(year, start, end, fmt):
    """Re-serialize the chosen window as a querystring for the PDF link."""
    parts = []
    if year is not None:
        parts.append(f"year={year}")
    else:
        parts.append(f"start={start.isoformat()}")
        parts.append(f"end={end.isoformat()}")
    parts.append(f"format={fmt}")
    return "&".join(parts)
