"""
Stock CRUD views: master-record create + asset transactions
(add/edit/delete) + per-symbol detail. The legacy ``stock_list_view`` is
kept for direct rendering of the per-kind list template; the modern UI
routes through the unified ``holdings_view``.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from ..forms import StockAssetForm, StockMasterForm
from ..services import compute_stock_tax
from ._helpers import (
    _add_view,
    _delete_view,
    _detail_view,
    _edit_view,
    _instrument_create_view,
    _list_view,
)


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


@login_required
def stock_list_redirect(request):
    """Legacy route → unified Holdings filtered to stocks."""
    return redirect("/holdings/?kind=stock")
