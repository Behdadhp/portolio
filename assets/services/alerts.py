"""
Price-alert cache sync. The Celery price-stream worker reads this Redis
key on every tick and fans matching alerts out to email — so this needs
to be called whenever a PriceAlert is created or deleted.
"""

from django.core.cache import cache


def sync_alert_cache():
    """Rebuild the Redis alert cache from the DB."""
    from ..models import PriceAlert

    alerts = PriceAlert.objects.filter(email_sent=False).select_related("instrument")
    alert_data = {}
    for a in alerts:
        if a.instrument_id is None:
            continue
        alert_data.setdefault(a.instrument.symbol, []).append(
            {
                "id": str(a.id),
                "user_id": str(a.user_id),
                "target_price": float(a.target_price),
                "direction": a.direction,
                "invest_amount": (
                    float(a.invest_amount) if a.invest_amount is not None else None
                ),
            }
        )
    cache.set("price_alerts_active", alert_data, timeout=None)
