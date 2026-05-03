"""
Cash-flow rollups + portfolio-worth helpers used by the dashboard,
the cash list page, and the analytics report.
"""

from django.core.cache import cache
from django.db.models import Sum

from .helpers import get_asset_summary


def get_cash_summary(user):
    """
    Return totals for a user's cash deposits/withdrawals (all USD).

    `net_invested_usd` is the principal still committed to the brokerage:
    deposits − withdrawals.
    """
    from ..models import CashFlow

    flows = CashFlow.objects.filter(user=user)
    deposits = float(
        flows.filter(direction="deposit").aggregate(s=Sum("amount_usd"))["s"] or 0
    )
    withdrawals = float(
        flows.filter(direction="withdraw").aggregate(s=Sum("amount_usd"))["s"] or 0
    )
    return {
        "deposits_usd": round(deposits, 2),
        "withdrawals_usd": round(withdrawals, 2),
        "net_invested_usd": round(deposits - withdrawals, 2),
    }


def get_total_portfolio_worth_usd(user):
    """
    Sum the user's current holdings (all kinds) in USD using the price cache.
    """
    from ..models import Transaction

    total = 0.0
    for row in get_asset_summary(Transaction.objects.filter(user=user)):
        amt = float(row["total"])
        if amt <= 0:
            continue
        price = cache.get(f"finnhub_{row['symbol']}")
        if price is None:
            continue
        total += amt * float(price)
    return round(total, 2)
