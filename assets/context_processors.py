from django.core.cache import cache


def fx_status(request):
    """Expose FX-rate availability so templates can show a banner when EUR/USD is missing."""
    return {"eur_rate_unavailable": bool(cache.get("fx_eur_usd_unavailable"))}


def topbar(request):
    """Live portfolio value for the global topbar."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    from .services import get_total_portfolio_worth_usd

    try:
        return {"topbar_portfolio_value": get_total_portfolio_worth_usd(request.user)}
    except Exception:
        return {"topbar_portfolio_value": None}
