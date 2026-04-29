from django.core.cache import cache


def fx_status(request):
    """Expose FX-rate availability so templates can show a banner when EUR/USD is missing."""
    return {"eur_rate_unavailable": bool(cache.get("fx_eur_usd_unavailable"))}
