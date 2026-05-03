"""
Crypto CRUD views: master-record create + asset transactions + detail.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from ..forms import CryptoAssetForm, CryptoMasterForm
from ..services import compute_crypto_tax
from ._helpers import (
    _add_view,
    _delete_view,
    _detail_view,
    _edit_view,
    _instrument_create_view,
    _list_view,
)


@login_required
def crypto_list_view(request):
    return _list_view(request, "crypto", "assets/crypto_list.html", "cryptos")


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


@login_required
def crypto_list_redirect(request):
    """Legacy route → unified Holdings filtered to crypto."""
    return redirect("/holdings/?kind=crypto")
