"""
JSON API views: instrument lookup (Finnhub probe used by the master-create
form) and the global Cmd-K search.
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse

from ..models import Instrument
from ..services import lookup_instrument


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


@login_required
def search_view(request):
    """JSON endpoint for the Cmd-K palette."""
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    from django.db.models import Q
    from django.urls import reverse

    results = []
    detail_route = {"stock": "stock_detail", "etf": "etf_detail", "crypto": "crypto_detail"}

    instruments = Instrument.objects.filter(
        Q(symbol__icontains=q) | Q(name__icontains=q)
    )[:8]
    for inst in instruments:
        results.append({
            "kind": inst.kind,
            "type": "instrument",
            "label": inst.name,
            "sub": inst.symbol,
            "url": reverse(detail_route[inst.kind], args=[inst.symbol]),
        })

    # Quick-action shortcuts surfaced for likely queries.
    shortcuts = [
        ("dashboard", "Dashboard", "/dashboard/"),
        ("holdings", "Holdings", "/holdings/"),
        ("transactions", "Transactions", "/transactions/"),
        ("alerts", "Alerts", "/alerts/"),
        ("market", "Market", "/market/"),
        ("watchlist", "Watchlist", "/watchlist/"),
        ("cash", "Cash", "/cash/"),
    ]
    ql = q.lower()
    for keyword, label, url in shortcuts:
        if keyword.startswith(ql) or ql in keyword:
            results.append({
                "kind": "page",
                "type": "shortcut",
                "label": label,
                "sub": "Open page",
                "url": url,
            })

    return JsonResponse({"results": results[:12]})
