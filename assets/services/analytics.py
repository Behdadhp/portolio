"""
Per-asset analytics: weighted-average cost basis, holdings, P&L, and
target/simulator price points used by stock/ETF/crypto detail pages.
"""

from django.core.cache import cache


def compute_analytics(transactions, symbol):
    """
    Compute portfolio analytics from a chronologically ordered list of transactions.

    Uses weighted-average cost basis: buys increase cost basis (price × amount
    + buy fee), sells reduce units but do NOT change the average (cost basis
    reduced proportionally). Sell fees come off the realized proceeds.

    Returns a dict with all analytics, or None if no holdings.
    """
    cost_basis = 0.0
    units = 0.0

    total_invested = 0.0
    total_sold_value = 0.0
    total_sold_units = 0.0

    for tx in transactions.order_by("date", "status", "pk"):
        amt = float(tx.amount)
        px = float(tx.price)
        fee = float(tx.fee or 0)

        if tx.status == "bought":
            cost_basis += amt * px + fee
            units += amt
            total_invested += amt * px + fee
        elif tx.status == "sold":
            if units > 0:
                avg = cost_basis / units
                cost_basis -= amt * avg
                units -= amt
            total_sold_value += amt * px - fee
            total_sold_units += amt

    if units <= 0:
        return {
            "warning": "sold_more_than_bought" if units < 0 else "no_holdings",
            "units": round(units, 6),
            "total_invested": round(total_invested, 2),
            "total_sold_value": round(total_sold_value, 2),
            "realized_pnl": (
                round(
                    total_sold_value
                    - total_sold_units
                    * (total_invested / max(total_sold_units + units, 0.0001)),
                    2,
                )
                if total_sold_units > 0
                else 0.0
            ),
        }

    avg_price = cost_basis / units
    current_price = cache.get(f"finnhub_{symbol}")

    analytics = {
        "avg_price": round(avg_price, 2),
        "units": round(units, 6),
        "cost_basis": round(cost_basis, 2),
        "total_invested": round(total_invested, 2),
        "total_sold_value": round(total_sold_value, 2),
        "realized_pnl": (
            round(total_sold_value - total_sold_units * avg_price, 2)
            if total_sold_units > 0
            else 0.0
        ),
        "current_price": None,
        "current_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "sell_5": None,
        "sell_10": None,
        "sell_25": None,
        "buy_avg_minus_10": None,
        "buy_avg_minus_10_spend": None,
    }

    if current_price is not None:
        cp = float(current_price)
        current_value = units * cp
        unrealized_pnl = current_value - cost_basis
        unrealized_pnl_pct = (
            (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
        )

        analytics["current_price"] = round(cp, 2)
        analytics["current_value"] = round(current_value, 2)
        analytics["unrealized_pnl"] = round(unrealized_pnl, 2)
        analytics["unrealized_pnl_pct"] = round(unrealized_pnl_pct, 2)

        analytics["sell_5"] = round(avg_price * 1.05, 2)
        analytics["sell_10"] = round(avg_price * 1.10, 2)
        analytics["sell_25"] = round(avg_price * 1.25, 2)

        target_avg = avg_price * 0.90
        buy_price_for_minus_10 = (target_avg * (units * 2) - cost_basis) / units
        analytics["buy_avg_minus_10"] = (
            round(buy_price_for_minus_10, 2) if buy_price_for_minus_10 > 0 else 0.0
        )
        analytics["buy_avg_minus_10_spend"] = (
            round(buy_price_for_minus_10 * units, 2)
            if buy_price_for_minus_10 > 0
            else 0.0
        )

    return analytics


def cost_basis_for(txs):
    """
    Weighted-average remaining cost basis for a queryset of buy/sell
    transactions. Buy fees increase the basis; sell fees do not (they hit
    realized P&L instead, not the basis of remaining units).
    """
    cb = 0.0
    units = 0.0
    for tx in txs.order_by("date", "status", "pk"):
        amt = float(tx.amount)
        px = float(tx.price)
        fee = float(tx.fee or 0)
        if tx.status == "bought":
            cb += amt * px + fee
            units += amt
        elif tx.status == "sold" and units > 0:
            avg = cb / units
            cb -= amt * avg
            units -= amt
    return round(cb, 2)
