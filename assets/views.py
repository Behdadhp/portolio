import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    CryptoAssetForm,
    ETFAssetForm,
    ETFForm,
    ETFSavingsPlanForm,
    StockAssetForm,
)
from .models import (
    ETF,
    Crypto,
    CryptoAsset,
    ETFAsset,
    ETFSavingsPlan,
    PriceAlert,
    Stock,
    StockAsset,
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
    get_eur_usd_rate,
    get_filter_ranges,
    sort_and_paginate,
    sync_alert_cache,
)

# ── Generic CRUD helpers ─────────────────────────────────────


def _list_view(
    request,
    transaction_model,
    name_field,
    symbol_field,
    template,
    context_key,
    extra_rows=None,
):
    summary = get_asset_summary(
        transaction_model.objects.filter(user=request.user),
        name_field,
        symbol_field,
    )
    fk_field = symbol_field.split("__")[0]
    enriched = []
    allocation = []
    pnl_ranking = []
    for row in summary:
        price = cache.get(f"finnhub_{row['symbol']}")
        row["price"] = price
        amt = float(row["total"])
        row["worth"] = (
            round(amt * float(price), 2) if price is not None else None
        )
        enriched.append(row)
        worth = (
            round(amt * float(price), 2)
            if price is not None and amt > 0
            else 0
        )
        allocation.append(
            {"label": row["name"], "symbol": row["symbol"], "value": worth}
        )
        if price is not None and amt > 0:
            cb = cost_basis_for(
                transaction_model.objects.filter(
                    user=request.user,
                    **{f"{fk_field}__symbol": row["symbol"]},
                )
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


def _detail_view(
    request,
    symbol,
    master_model,
    transaction_model,
    fk_field,
    name_field,
    symbol_field,
    template,
    extra_context=None,
):
    master = get_object_or_404(master_model, symbol=symbol)
    base_qs = transaction_model.objects.filter(user=request.user, **{fk_field: master})

    summary = get_asset_summary(base_qs, name_field, symbol_field).first()
    total = summary["total"] if summary else 0

    analytics = compute_analytics(base_qs, symbol)

    ranges = get_filter_ranges(base_qs)
    transactions, filters = apply_filters(request, base_qs.order_by("-date"))
    page_obj, current_sort, current_order, per_page = sort_and_paginate(
        request, transactions
    )

    # Active price alerts for this asset
    alert_filter = {"user": request.user, fk_field: master}
    active_alerts = PriceAlert.objects.filter(**alert_filter).select_related(
        "stock", "crypto"
    )

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
        "active_alerts": active_alerts,
        **ranges,
    }
    if extra_context:
        context.update(extra_context)
    return render(request, template, context)


def _add_view(
    request, form_class, master_model, fk_field, template, detail_url, symbol=None
):
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

    return render(
        request,
        template,
        {
            "form": form,
            fk_field: master,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


def _edit_view(
    request, pk, form_class, transaction_model, fk_field, template, detail_url
):
    transaction = get_object_or_404(transaction_model, pk=pk, user=request.user)
    form = form_class(instance=transaction)

    if request.method == "POST":
        form = form_class(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect(detail_url, symbol=getattr(transaction, fk_field).symbol)

    master = getattr(transaction, fk_field)
    return render(
        request,
        template,
        {
            "form": form,
            "transaction": transaction,
            fk_field: master,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


def _delete_view(
    request, pk, transaction_model, fk_field, template, list_url, detail_url
):
    transaction = get_object_or_404(transaction_model, pk=pk, user=request.user)
    master = getattr(transaction, fk_field)

    if request.method == "POST":
        transaction.delete()
        if not transaction_model.objects.filter(
            user=request.user, **{fk_field: master}
        ).exists():
            return redirect(list_url)
        return redirect(detail_url, symbol=master.symbol)

    return render(request, template, {"transaction": transaction, fk_field: master})


# ── Stock views ──────────────────────────────────────────────


@login_required
def stock_list_view(request):
    return _list_view(
        request,
        StockAsset,
        "stock__name",
        "stock__symbol",
        "assets/stock_list.html",
        "stocks",
    )


@login_required
def stock_detail_view(request, symbol):
    tax = compute_stock_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request,
        symbol,
        Stock,
        StockAsset,
        "stock",
        "stock__name",
        "stock__symbol",
        "assets/stock_detail.html",
        extra_context={"tax": tax},
    )


@login_required
def stock_add_view(request, symbol=None):
    return _add_view(
        request,
        StockAssetForm,
        Stock,
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
        StockAsset,
        "stock",
        "assets/stock_edit.html",
        "stock_detail",
    )


@login_required
def stock_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        StockAsset,
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
    etf = get_object_or_404(ETF, symbol=symbol)
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
    plan_etfs = ETF.objects.filter(savings_plans__user=request.user).distinct()
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
        ETFAsset,
        "etf__name",
        "etf__symbol",
        "assets/etf_list.html",
        "etfs",
        extra_rows=extra_rows,
    )


@login_required
def etf_detail_view(request, symbol):
    tax = compute_etf_tax(request.user, current_symbol=symbol)
    etf = get_object_or_404(ETF, symbol=symbol)
    savings_plans = ETFSavingsPlan.objects.filter(user=request.user, etf=etf)
    return _detail_view(
        request,
        symbol,
        ETF,
        ETFAsset,
        "etf",
        "etf__name",
        "etf__symbol",
        "assets/etf_detail.html",
        extra_context={"tax": tax, "savings_plans": savings_plans},
    )


# ── ETF Savings Plan views ──────────────────────────────────


@login_required
def etf_plan_create_view(request, symbol=None):
    initial = {}
    etf = None
    if symbol:
        etf = get_object_or_404(ETF, symbol=symbol)
        initial["etf"] = etf

    form = ETFSavingsPlanForm(initial=initial)

    if request.method == "POST":
        form = ETFSavingsPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.user = request.user
            plan.next_execution_date = plan.start_date
            plan.save()
            return redirect("etf_detail", symbol=plan.etf.symbol)

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
            # If start_date changed and plan hasn't run yet, realign next_execution_date.
            if (
                "start_date" in form.changed_data
                and updated.last_executed_at is None
            ):
                updated.next_execution_date = updated.start_date
            updated.save()
            return redirect("etf_detail", symbol=updated.etf.symbol)

    return render(
        request,
        "assets/etf_plan_form.html",
        {
            "form": form,
            "etf": plan.etf,
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
    return redirect("etf_detail", symbol=plan.etf.symbol)


@login_required
def etf_plan_delete_view(request, pk):
    plan = get_object_or_404(ETFSavingsPlan, pk=pk, user=request.user)
    etf = plan.etf
    if request.method == "POST":
        plan.delete()
        return redirect("etf_detail", symbol=etf.symbol)
    return render(request, "assets/etf_plan_delete.html", {"plan": plan, "etf": etf})


def _refresh_etf_last_price(etf):
    """
    Mirror the most recent transaction's price onto the master ETF.

    Picks the latest by (date, pk) across all users so historical inserts/edits
    don't clobber a more recent price.
    """
    latest = etf.transactions.order_by("-date", "-pk").first()
    new_price = latest.price if latest else None
    if new_price != etf.last_price:
        etf.last_price = new_price
        etf.save(update_fields=["last_price"])


@login_required
def etf_add_view(request, symbol=None):
    initial = {}
    etf = None
    if symbol:
        etf = get_object_or_404(ETF, symbol=symbol)
        initial["etf"] = etf

    form = ETFAssetForm(initial=initial)

    if request.method == "POST":
        form = ETFAssetForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            _refresh_etf_last_price(transaction.etf)
            return redirect("etf_detail", symbol=transaction.etf.symbol)

    return render(
        request,
        "assets/etf_add.html",
        {"form": form, "etf": etf, "eur_usd_rate": get_eur_usd_rate()},
    )


@login_required
def etf_edit_view(request, pk):
    transaction = get_object_or_404(ETFAsset, pk=pk, user=request.user)
    form = ETFAssetForm(instance=transaction)

    if request.method == "POST":
        form = ETFAssetForm(request.POST, instance=transaction)
        if form.is_valid():
            transaction = form.save()
            _refresh_etf_last_price(transaction.etf)
            return redirect("etf_detail", symbol=transaction.etf.symbol)

    return render(
        request,
        "assets/etf_edit.html",
        {
            "form": form,
            "transaction": transaction,
            "etf": transaction.etf,
            "eur_usd_rate": get_eur_usd_rate(),
        },
    )


@login_required
def etf_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        ETFAsset,
        "etf",
        "assets/etf_delete.html",
        "etfs",
        "etf_detail",
    )


# ── Crypto views ─────────────────────────────────────────────


@login_required
def crypto_list_view(request):
    return _list_view(
        request,
        CryptoAsset,
        "crypto__name",
        "crypto__symbol",
        "assets/crypto_list.html",
        "cryptos",
    )


@login_required
def crypto_detail_view(request, symbol):
    crypto_tax = compute_crypto_tax(request.user, current_symbol=symbol)
    return _detail_view(
        request,
        symbol,
        Crypto,
        CryptoAsset,
        "crypto",
        "crypto__name",
        "crypto__symbol",
        "assets/crypto_detail.html",
        extra_context={"crypto_tax": crypto_tax},
    )


@login_required
def crypto_add_view(request, symbol=None):
    return _add_view(
        request,
        CryptoAssetForm,
        Crypto,
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
        CryptoAsset,
        "crypto",
        "assets/crypto_edit.html",
        "crypto_detail",
    )


@login_required
def crypto_delete_view(request, pk):
    return _delete_view(
        request,
        pk,
        CryptoAsset,
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

    # invest_amount is only meaningful for buy (below) alerts
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

    # Find the asset
    stock = Stock.objects.filter(symbol=symbol).first()
    etf = ETF.objects.filter(symbol=symbol).first() if not stock else None
    crypto = (
        Crypto.objects.filter(symbol=symbol).first()
        if not stock and not etf
        else None
    )

    if not stock and not etf and not crypto:
        return JsonResponse(
            {"error": f"No asset found for symbol '{symbol}'"}, status=404
        )

    # Proximity check: any active alert within 1% of this price?
    existing = PriceAlert.objects.filter(
        user=request.user,
        stock=stock,
        etf=etf,
        crypto=crypto,
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
        stock=stock,
        etf=etf,
        crypto=crypto,
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
