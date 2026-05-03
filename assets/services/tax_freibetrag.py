"""
German Sparer-Pauschbetrag (Freibetrag) tax computation for stocks and
ETFs. Weighted-average cost basis, fees baked into basis on buys and
deducted from proceeds on sells. The internal helper does the math; the
public ``compute_stock_tax`` / ``compute_etf_tax`` wrappers select the
``kind`` and result-key prefix.
"""

from .prices import get_eur_usd_rate


def _compute_freibetrag_tax(user, kind, current_symbol, key_prefix):
    """
    Shared weighted-average tax calculator for stocks and ETFs.

    German rules: 26.375% on gains above €1,000 Freibetrag.
    Losses can only offset gains within the same kind.
    """
    from datetime import date

    from ..models import Transaction

    TAX_RATE = 0.26375
    FREIBETRAG_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIBETRAG = FREIBETRAG_EUR * eur_usd
    current_year = date.today().year

    qs = Transaction.objects.filter(user=user, instrument__kind=kind)
    # Strip default ordering before DISTINCT — Transaction.Meta.ordering leaks
    # into the SELECT and yields duplicate instrument_ids, double-counting
    # gains for any user who has more than one transaction per instrument.
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    total_gains = 0.0
    total_losses = 0.0
    current_gains = 0.0
    current_losses = 0.0
    sell_count = 0

    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        cost_basis = 0.0
        units = 0.0

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                cost_basis += amt * px + fee
                units += amt
            elif tx.status == "sold" and units > 0:
                avg = cost_basis / units
                pnl = (px - avg) * amt - fee
                cost_basis -= amt * avg
                units -= amt

                if tx.date.year == current_year:
                    if pnl >= 0:
                        total_gains += pnl
                    else:
                        total_losses += abs(pnl)

                    if symbol == current_symbol:
                        if pnl >= 0:
                            current_gains += pnl
                        else:
                            current_losses += abs(pnl)

                    sell_count += 1

    net_gain = total_gains - total_losses
    taxable = max(0.0, net_gain - FREIBETRAG)
    tax_owed = taxable * TAX_RATE
    freibetrag_used = min(net_gain, FREIBETRAG) if net_gain > 0 else 0.0
    freibetrag_remaining = FREIBETRAG - freibetrag_used
    gain_until_taxed = max(0.0, FREIBETRAG - net_gain) if net_gain < FREIBETRAG else 0.0
    current_net = current_gains - current_losses

    return {
        "year": current_year,
        "total_gains": round(total_gains, 2),
        "total_losses": round(total_losses, 2),
        "net_gain": round(net_gain, 2),
        "freibetrag": FREIBETRAG,
        "freibetrag_used": round(freibetrag_used, 2),
        "freibetrag_remaining": round(freibetrag_remaining, 2),
        "gain_until_taxed": round(gain_until_taxed, 2),
        "taxable": round(taxable, 2),
        "tax_rate_pct": round(TAX_RATE * 100, 3),
        "tax_owed": round(tax_owed, 2),
        "net_after_tax": round(net_gain - tax_owed, 2),
        f"current_{key_prefix}_gains": round(current_gains, 2),
        f"current_{key_prefix}_losses": round(current_losses, 2),
        f"current_{key_prefix}_net": round(current_net, 2),
        "sell_count": sell_count,
    }


def compute_stock_tax(user, current_symbol=None):
    """German stock capital-gains tax for the current year (Freibetrag €1,000)."""
    return _compute_freibetrag_tax(user, "stock", current_symbol, "stock")


def compute_etf_tax(user, current_symbol=None):
    """German ETF capital-gains tax for the current year (Freibetrag €1,000)."""
    return _compute_freibetrag_tax(user, "etf", current_symbol, "etf")
