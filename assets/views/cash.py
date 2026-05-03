"""
Cash flow CRUD: deposits and withdrawals plus a list page that totals
real-money P&L (portfolio worth − net invested).
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import CashFlowForm
from ..models import CashFlow
from ..services import get_cash_summary, get_eur_usd_rate, get_total_portfolio_worth_usd


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
