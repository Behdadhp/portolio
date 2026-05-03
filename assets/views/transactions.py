"""
Unified ledger page across all asset transactions and cash flows.
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from ..models import CashFlow, Transaction
from ._helpers import KIND_CHOICES


@login_required
def transactions_view(request):
    """Unified ledger across asset transactions and cash flows."""
    kind = request.GET.get("kind", "all")
    action = request.GET.get("action", "all")

    asset_qs = Transaction.objects.filter(user=request.user).select_related("instrument")
    cash_qs = CashFlow.objects.filter(user=request.user)

    if kind in ("stock", "etf", "crypto"):
        asset_qs = asset_qs.filter(instrument__kind=kind)
        cash_qs = cash_qs.none()
    elif kind == "cash":
        asset_qs = asset_qs.none()
    elif kind != "all":
        kind = "all"

    if action in ("bought", "sold"):
        asset_qs = asset_qs.filter(status=action)
        cash_qs = cash_qs.none()
    elif action in ("deposit", "withdraw"):
        asset_qs = asset_qs.none()
        cash_qs = cash_qs.filter(direction=action)
    elif action != "all":
        action = "all"

    rows = []
    edit_route = {"stock": "stock_edit", "etf": "etf_edit", "crypto": "crypto_edit"}
    detail_route = {"stock": "stock_detail", "etf": "etf_detail", "crypto": "crypto_detail"}
    for tx in asset_qs:
        rows.append({
            "type": "asset",
            "date": tx.date,
            "kind": tx.instrument.kind,
            "symbol": tx.instrument.symbol,
            "name": tx.instrument.name,
            "action": tx.status,
            "amount": float(tx.amount),
            "price": float(tx.price),
            "value_usd": round(float(tx.amount) * float(tx.price), 2),
            "edit_route": edit_route[tx.instrument.kind],
            "detail_route": detail_route[tx.instrument.kind],
            "pk": tx.pk,
        })
    for cf in cash_qs:
        rows.append({
            "type": "cash",
            "date": cf.date,
            "action": cf.direction,
            "amount_usd": float(cf.amount_usd),
            "note": cf.note,
            "pk": cf.pk,
        })

    rows.sort(key=lambda r: r["date"], reverse=True)

    paginator = Paginator(rows, 30)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "assets/transactions.html", {
        "page_obj": page_obj,
        "current_kind": kind,
        "current_action": action,
        "kind_choices": KIND_CHOICES + [("cash", "Cash")],
    })
