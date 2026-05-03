"""
ETF CRUD views — master record create/edit, asset-transaction CRUD, the
per-symbol detail page, and the four ETFSavingsPlan views (create, edit,
toggle active, delete).
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ETFAssetForm, ETFForm, ETFSavingsPlanForm
from ..models import ETFSavingsPlan, Instrument, Transaction
from ..services import compute_etf_tax, get_eur_usd_rate, refresh_instrument_last_price
from ._helpers import _delete_view, _detail_view, _list_view


# ── Master record (create + edit) ───────────────────────────


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


# ── List + detail ───────────────────────────────────────────


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


# ── ETF Savings Plans ──────────────────────────────────────


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


# ── ETF transactions (add/edit/delete) ─────────────────────


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


@login_required
def etf_list_redirect(request):
    """Legacy route → unified Holdings filtered to ETFs."""
    return redirect("/holdings/?kind=etf")
