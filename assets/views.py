import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    CashFlowForm,
    CryptoAssetForm,
    CryptoMasterForm,
    ETFAssetForm,
    ETFForm,
    ETFSavingsPlanForm,
    StockAssetForm,
    StockMasterForm,
)
from .models import (
    CashFlow,
    ETFSavingsPlan,
    Instrument,
    PriceAlert,
    Transaction,
)
from .services import (
    DETAIL_COLUMNS,
    apply_filters,
    compute_analytics,
    compute_crypto_tax,
    compute_etf_tax,
    compute_stock_tax,
    cost_basis_for,
    get_asset_summary,
    get_cash_summary,
    get_eur_usd_rate,
    get_filter_ranges,
    get_total_portfolio_worth_usd,
    lookup_instrument,
    refresh_instrument_last_price,
    sort_and_paginate,
    sync_alert_cache,
)

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


# ── Instrument lookup API (Finnhub probe) ───────────────────


@login_required
def lookup_instrument_view(request):
    """
    GET /api/lookup-instrument/?kind=stock&symbol=AAPL

    Probes Finnhub to verify the symbol exists and returns canonical
    name + current price. Also flags if the user already has this
    instrument in their portfolio (so the UI can offer a link).
    """
    kind = request.GET.get("kind", "").strip().lower()
    symbol = request.GET.get("symbol", "").strip().upper()

    if kind not in ("stock", "crypto"):
        return JsonResponse(
            {"valid": False, "error": "kind must be 'stock' or 'crypto'."},
            status=400,
        )
    if not symbol:
        return JsonResponse(
            {"valid": False, "error": "Symbol is required."}, status=400
        )

    existing = Instrument.objects.filter(kind=kind, symbol=symbol).first()
    if existing is not None:
        detail_route = "stock_detail" if kind == "stock" else "crypto_detail"
        from django.urls import reverse

        return JsonResponse(
            {
                "valid": False,
                "exists_in_db": True,
                "error": f"'{symbol}' is already in your portfolio.",
                "existing_url": reverse(detail_route, args=[symbol]),
                "existing_name": existing.name,
            },
            status=409,
        )

    result = lookup_instrument(kind, symbol)
    return JsonResponse(result, status=200 if result["valid"] else 404)


# ── Stock views ──────────────────────────────────────────────


@login_required
def stock_list_view(request):
    return _list_view(request, "stock", "assets/stock_list.html", "stocks")


@login_required
def stock_create_view(request):
    return _instrument_create_view(
        request,
        kind="stock",
        form_class=StockMasterForm,
        list_route="stocks",
        detail_route="stock_detail",
        title="Add Stock",
    )


@login_required
def crypto_create_view(request):
    return _instrument_create_view(
        request,
        kind="crypto",
        form_class=CryptoMasterForm,
        list_route="crypto",
        detail_route="crypto_detail",
        title="Add Crypto",
    )


def _instrument_create_view(request, kind, form_class, list_route, detail_route, title):
    """
    Shared create flow for Stock and Crypto masters. Re-verifies the symbol
    against Finnhub on POST as defense-in-depth (the JS verify step in the
    UI is the primary check).
    """
    form = form_class()
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


@login_required
def stock_detail_view(request, symbol):
    tax = compute_stock_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request,
        symbol,
        "stock",
        "stock",
        "assets/stock_detail.html",
        extra_context={"tax": tax},
    )


@login_required
def stock_add_view(request, symbol=None):
    return _add_view(
        request,
        StockAssetForm,
        "stock",
        "stock",
        "assets/stock_add.html",
        "stock_detail",
        symbol,
    )


@login_required
def stock_edit_view(request, pk):
    return _edit_view(
        request,
        pk,
        StockAssetForm,
        "stock",
        "stock",
        "assets/stock_edit.html",
        "stock_detail",
    )


@login_required
def stock_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        "stock",
        "stock",
        "assets/stock_delete.html",
        "stocks",
        "stock_detail",
    )


# ── ETF views ────────────────────────────────────────────────


@login_required
def etf_create_view(request):
    form = ETFForm()
    if request.method == "POST":
        form = ETFForm(request.POST)
        if form.is_valid():
            etf = form.save()
            return redirect("etf_detail", symbol=etf.symbol)
    return render(
        request,
        "assets/etf_master_form.html",
        {"form": form, "mode": "create", "eur_usd_rate": get_eur_usd_rate()},
    )


@login_required
def etf_master_edit_view(request, symbol):
    etf = get_object_or_404(Instrument, kind="etf", symbol=symbol)
    form = ETFForm(instance=etf)
    if request.method == "POST":
        form = ETFForm(request.POST, instance=etf)
        if form.is_valid():
            etf = form.save()
            return redirect("etf_detail", symbol=etf.symbol)
    return render(
        request,
        "assets/etf_master_form.html",
        {
            "form": form,
            "etf": etf,
            "mode": "edit",
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def etf_list_view(request):
    # Surface ETFs the user has a savings plan for (or that they just added
    # without any transactions yet) so the detail page stays reachable.
    plan_etfs = Instrument.objects.filter(
        kind="etf", savings_plans__user=request.user
    ).distinct()
    extra_rows = [
        {
            "name": etf.name,
            "symbol": etf.symbol,
            "total": 0.0,
            "price": cache.get(f"finnhub_{etf.symbol}"),
            "worth": None,
        }
        for etf in plan_etfs
    ]
    return _list_view(
        request,
        "etf",
        "assets/etf_list.html",
        "etfs",
        extra_rows=extra_rows,
    )


@login_required
def etf_detail_view(request, symbol):
    tax = compute_etf_tax(request.user, current_symbol=symbol)
    etf = get_object_or_404(Instrument, kind="etf", symbol=symbol)
    savings_plans = ETFSavingsPlan.objects.filter(user=request.user, instrument=etf)
    return _detail_view(
        request,
        symbol,
        "etf",
        "etf",
        "assets/etf_detail.html",
        extra_context={"tax": tax, "savings_plans": savings_plans},
    )


# ── ETF Savings Plan views ──────────────────────────────────


@login_required
def etf_plan_create_view(request, symbol=None):
    initial = {}
    etf = None
    if symbol:
        etf = get_object_or_404(Instrument, kind="etf", symbol=symbol)
        initial["etf"] = etf

    form = ETFSavingsPlanForm(initial=initial)

    if request.method == "POST":
        form = ETFSavingsPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.user = request.user
            plan.next_execution_date = plan.start_date
            plan.save()
            return redirect("etf_detail", symbol=plan.instrument.symbol)

    return render(
        request,
        "assets/etf_plan_form.html",
        {
            "form": form,
            "etf": etf,
            "mode": "create",
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def etf_plan_edit_view(request, pk):
    plan = get_object_or_404(ETFSavingsPlan, pk=pk, user=request.user)
    form = ETFSavingsPlanForm(instance=plan)

    if request.method == "POST":
        form = ETFSavingsPlanForm(request.POST, instance=plan)
        if form.is_valid():
            updated = form.save(commit=False)
            if (
                "start_date" in form.changed_data
                and updated.last_executed_at is None
            ):
                updated.next_execution_date = updated.start_date
            updated.save()
            return redirect("etf_detail", symbol=updated.instrument.symbol)

    return render(
        request,
        "assets/etf_plan_form.html",
        {
            "form": form,
            "etf": plan.instrument,
            "plan": plan,
            "mode": "edit",
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
@require_POST
def etf_plan_toggle_view(request, pk):
    plan = get_object_or_404(ETFSavingsPlan, pk=pk, user=request.user)
    plan.active = not plan.active
    plan.save(update_fields=["active"])
    return redirect("etf_detail", symbol=plan.instrument.symbol)


@login_required
def etf_plan_delete_view(request, pk):
    plan = get_object_or_404(ETFSavingsPlan, pk=pk, user=request.user)
    etf = plan.instrument
    if request.method == "POST":
        plan.delete()
        return redirect("etf_detail", symbol=etf.symbol)
    return render(request, "assets/etf_plan_delete.html", {"plan": plan, "etf": etf})


@login_required
def etf_add_view(request, symbol=None):
    initial = {}
    etf = None
    if symbol:
        etf = get_object_or_404(Instrument, kind="etf", symbol=symbol)
        initial["etf"] = etf

    form = ETFAssetForm(initial=initial)

    if request.method == "POST":
        form = ETFAssetForm(request.POST)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.user = request.user
            tx.save()
            refresh_instrument_last_price(tx.instrument)
            return redirect("etf_detail", symbol=tx.instrument.symbol)

    return render(
        request,
        "assets/etf_add.html",
        {"form": form, "etf": etf, "eur_usd_rate": get_eur_usd_rate()},
    )


@login_required
def etf_edit_view(request, pk):
    tx = get_object_or_404(
        Transaction, pk=pk, user=request.user, instrument__kind="etf"
    )
    form = ETFAssetForm(instance=tx)

    if request.method == "POST":
        form = ETFAssetForm(request.POST, instance=tx)
        if form.is_valid():
            tx = form.save()
            refresh_instrument_last_price(tx.instrument)
            return redirect("etf_detail", symbol=tx.instrument.symbol)

    return render(
        request,
        "assets/etf_edit.html",
        {
            "form": form,
            "transaction": tx,
            "etf": tx.instrument,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def etf_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        "etf",
        "etf",
        "assets/etf_delete.html",
        "etfs",
        "etf_detail",
    )


# ── Crypto views ─────────────────────────────────────────────


@login_required
def crypto_list_view(request):
    return _list_view(request, "crypto", "assets/crypto_list.html", "cryptos")


@login_required
def crypto_detail_view(request, symbol):
    crypto_tax = compute_crypto_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request,
        symbol,
        "crypto",
        "crypto",
        "assets/crypto_detail.html",
        extra_context={"crypto_tax": crypto_tax},
    )


@login_required
def crypto_add_view(request, symbol=None):
    return _add_view(
        request,
        CryptoAssetForm,
        "crypto",
        "crypto",
        "assets/crypto_add.html",
        "crypto_detail",
        symbol,
    )


@login_required
def crypto_edit_view(request, pk):
    return _edit_view(
        request,
        pk,
        CryptoAssetForm,
        "crypto",
        "crypto",
        "assets/crypto_edit.html",
        "crypto_detail",
    )


@login_required
def crypto_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        "crypto",
        "crypto",
        "assets/crypto_delete.html",
        "crypto",
        "crypto_detail",
    )


# ── Price Alert API ─────────────────────────────────────────

ALERT_PROXIMITY_PCT = 1.0  # alerts within 1% are considered duplicates


@login_required
@require_POST
def alert_create(request):
    """Create a price alert. Returns JSON."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    symbol = data.get("symbol", "").strip()
    target_price = data.get("target_price")
    direction = data.get("direction", "above")
    invest_amount = data.get("invest_amount")

    if not symbol or target_price is None:
        return JsonResponse({"error": "symbol and target_price required"}, status=400)

    try:
        target_price = float(target_price)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid target_price"}, status=400)

    if target_price <= 0:
        return JsonResponse({"error": "target_price must be positive"}, status=400)

    if direction not in ("above", "below"):
        return JsonResponse(
            {"error": "direction must be 'above' or 'below'"}, status=400
        )

    if direction == "below" and invest_amount is not None:
        try:
            invest_amount = float(invest_amount)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid invest_amount"}, status=400)
        if invest_amount <= 0:
            return JsonResponse(
                {"error": "invest_amount must be positive"}, status=400
            )
    else:
        invest_amount = None

    # Find the instrument (any kind) by symbol.
    instrument = Instrument.objects.filter(symbol=symbol).first()
    if instrument is None:
        return JsonResponse(
            {"error": f"No asset found for symbol '{symbol}'"}, status=404
        )

    existing = PriceAlert.objects.filter(
        user=request.user,
        instrument=instrument,
        direction=direction,
        email_sent=False,
    )
    for alert in existing:
        pct_diff = abs(float(alert.target_price) - target_price) / target_price * 100
        if pct_diff < ALERT_PROXIMITY_PCT:
            return JsonResponse(
                {
                    "error": "duplicate",
                    "message": f"An alert already exists at ${float(alert.target_price):,.2f} (within 1% of ${target_price:,.2f}).",
                    "existing_id": str(alert.id),
                    "existing_price": float(alert.target_price),
                },
                status=409,
            )

    alert = PriceAlert.objects.create(
        user=request.user,
        instrument=instrument,
        target_price=target_price,
        direction=direction,
        invest_amount=invest_amount,
    )
    sync_alert_cache()

    return JsonResponse(
        {
            "id": str(alert.id),
            "target_price": float(alert.target_price),
            "direction": alert.direction,
            "invest_amount": (
                float(alert.invest_amount) if alert.invest_amount is not None else None
            ),
            "email_sent": alert.email_sent,
            "created_at": alert.created_at.strftime("%Y-%m-%d %H:%M"),
        },
        status=201,
    )


@login_required
@require_POST
def alert_delete(request, pk):
    """Delete a price alert."""
    alert = get_object_or_404(PriceAlert, pk=pk, user=request.user)
    alert.delete()
    sync_alert_cache()
    return JsonResponse({"deleted": True})


# ── Cash flow views ─────────────────────────────────────────


@login_required
def cash_list_view(request):
    flows = CashFlow.objects.filter(user=request.user)
    summary = get_cash_summary(request.user)
    portfolio_worth = get_total_portfolio_worth_usd(request.user)
    real_pnl = portfolio_worth - summary["net_invested_usd"]
    real_pnl_pct = (
        (real_pnl / summary["net_invested_usd"] * 100)
        if summary["net_invested_usd"] > 0
        else 0.0
    )
    return render(
        request,
        "assets/cash_list.html",
        {
            "flows": flows,
            "summary": summary,
            "portfolio_worth": portfolio_worth,
            "real_pnl": real_pnl,
            "real_pnl_pct": real_pnl_pct,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def cash_add_view(request):
    form = CashFlowForm()
    if request.method == "POST":
        form = CashFlowForm(request.POST)
        if form.is_valid():
            flow = form.save(commit=False)
            flow.user = request.user
            flow.save()
            return redirect("cash")
    return render(
        request,
        "assets/cash_form.html",
        {"form": form, "mode": "create", "eur_usd_rate": get_eur_usd_rate()},
    )


@login_required
def cash_edit_view(request, pk):
    flow = get_object_or_404(CashFlow, pk=pk, user=request.user)
    form = CashFlowForm(instance=flow)
    if request.method == "POST":
        form = CashFlowForm(request.POST, instance=flow)
        if form.is_valid():
            form.save()
            return redirect("cash")
    return render(
        request,
        "assets/cash_form.html",
        {
            "form": form,
            "flow": flow,
            "mode": "edit",
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def cash_delete_view(request, pk):
    flow = get_object_or_404(CashFlow, pk=pk, user=request.user)
    if request.method == "POST":
        flow.delete()
        return redirect("cash")
    return render(request, "assets/cash_delete.html", {"flow": flow})
