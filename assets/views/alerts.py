"""
Price alerts: list page with live distance-to-target annotation, plus
the JSON create / delete API used by the per-asset analytics card.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..models import Instrument, PriceAlert
from ..services import sync_alert_cache


ALERT_PROXIMITY_PCT = 1.0  # alerts within 1% are considered duplicates


@login_required
def alerts_view(request):
    alerts = (
        PriceAlert.objects.filter(user=request.user)
        .select_related("instrument")
        .order_by("email_sent", "-created_at")
    )
    # Annotate live price + distance to target.
    rows = []
    for a in alerts:
        symbol = a.instrument.symbol
        live = cache.get(f"finnhub_{symbol}")
        distance_pct = None
        if live is not None and a.target_price:
            distance_pct = round(
                (float(live) - float(a.target_price)) / float(a.target_price) * 100, 2
            )
        rows.append({
            "alert": a,
            "live_price": live,
            "distance_pct": distance_pct,
            "kind": a.instrument.kind,
        })
    return render(request, "assets/alerts.html", {"rows": rows})


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
