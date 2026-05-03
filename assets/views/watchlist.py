"""
Watchlist: list of starred instruments + a POST toggle that adds/removes
an entry. The Cmd-K search endpoint lives in ``api.py`` since it's a
JSON API rather than an HTML page.
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..models import Instrument, WatchlistEntry


@login_required
def watchlist_view(request):
    entries = (
        WatchlistEntry.objects.filter(user=request.user)
        .select_related("instrument")
        .order_by("-added_at")
    )
    rows = []
    for e in entries:
        sym = e.instrument.symbol
        live = cache.get(f"finnhub_{sym}")
        rows.append({
            "entry": e,
            "live_price": live,
        })
    return render(request, "assets/watchlist.html", {"rows": rows})


@login_required
@require_POST
def watchlist_toggle_view(request, instrument_id):
    instrument = get_object_or_404(Instrument, pk=instrument_id)
    entry = WatchlistEntry.objects.filter(
        user=request.user, instrument=instrument
    ).first()
    if entry is not None:
        entry.delete()
        return JsonResponse({"watching": False})
    WatchlistEntry.objects.create(user=request.user, instrument=instrument)
    return JsonResponse({"watching": True})
