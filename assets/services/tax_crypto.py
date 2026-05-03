"""
German crypto tax (FIFO) — §23 EStG private-sale rules. Lots held longer
than 365 days are tax-free. Short-term lots fall under the €1,000
Freigrenze: if exceeded, the whole short-term net becomes taxable at the
user's personal income-tax rate.
"""

from .prices import get_eur_usd_rate


def compute_crypto_tax(user, current_symbol=None):
    """
    Compute German crypto tax analytics for the current year.

    German crypto tax rules:
    - Hold > 1 year → completely tax-free on sale
    - Hold < 1 year → subject to income tax (Einkommensteuer)
    - Freigrenze: €1,000/year — if total short-term gains < €1,000, all tax-free
      (unlike Freibetrag: if you exceed €1,000, the ENTIRE amount is taxed)
    - Uses FIFO (First In, First Out) for determining holding period
    """
    from datetime import date, timedelta

    from ..models import Transaction

    FREIGRENZE_EUR = 1000.0
    eur_usd = get_eur_usd_rate() or 1.0
    FREIGRENZE = FREIGRENZE_EUR * eur_usd
    current_year = date.today().year
    today = date.today()

    qs = Transaction.objects.filter(user=user, instrument__kind="crypto")
    # See _compute_freibetrag_tax for why .order_by() is needed before .distinct().
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    total_short_term_gains = 0.0
    total_short_term_losses = 0.0
    total_long_term_gains = 0.0
    current_short_gains = 0.0
    current_short_losses = 0.0
    holding_lots = []

    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        lots = []

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                # Bake buy fee into the lot's per-unit price so cost basis
                # for FIFO remains correct without tracking fee separately.
                effective_price = px + (fee / amt if amt > 0 else 0)
                lots.append({"date": tx.date, "amount": amt, "price": effective_price})
            elif tx.status == "sold":
                # Allocate the sell fee proportionally across consumed lots.
                # `fee_per_unit` is the slice of this sell's fee borne by
                # each unit consumed below.
                fee_per_unit = (fee / amt) if amt > 0 else 0
                remaining_to_sell = amt
                while remaining_to_sell > 0 and lots:
                    lot = lots[0]
                    sell_from_lot = min(remaining_to_sell, lot["amount"])
                    holding_days = (tx.date - lot["date"]).days
                    pnl = (px - lot["price"]) * sell_from_lot - fee_per_unit * sell_from_lot

                    if tx.date.year == current_year:
                        if holding_days <= 365:
                            if pnl >= 0:
                                total_short_term_gains += pnl
                            else:
                                total_short_term_losses += abs(pnl)
                            if symbol == current_symbol:
                                if pnl >= 0:
                                    current_short_gains += pnl
                                else:
                                    current_short_losses += abs(pnl)
                        else:
                            total_long_term_gains += pnl if pnl > 0 else 0

                    lot["amount"] -= sell_from_lot
                    remaining_to_sell -= sell_from_lot
                    if lot["amount"] <= 0.0001:
                        lots.pop(0)

        if symbol == current_symbol:
            for lot in lots:
                if lot["amount"] > 0.0001:
                    tax_free_date = lot["date"] + timedelta(days=366)
                    days_left = (tax_free_date - today).days
                    holding_lots.append(
                        {
                            "buy_date": lot["date"],
                            "amount": round(lot["amount"], 8),
                            "price": round(lot["price"], 2),
                            "tax_free_date": tax_free_date,
                            "days_left": max(days_left, 0),
                            "is_tax_free": days_left <= 0,
                        }
                    )

    net_short_term = total_short_term_gains - total_short_term_losses
    current_net = current_short_gains - current_short_losses
    exceeds_freigrenze = net_short_term >= FREIGRENZE
    room_to_freigrenze = (
        max(0.0, FREIGRENZE - net_short_term) if not exceeds_freigrenze else 0.0
    )

    return {
        "year": current_year,
        "freigrenze": FREIGRENZE,
        "total_short_term_gains": round(total_short_term_gains, 2),
        "total_short_term_losses": round(total_short_term_losses, 2),
        "net_short_term": round(net_short_term, 2),
        "total_long_term_gains": round(total_long_term_gains, 2),
        "exceeds_freigrenze": exceeds_freigrenze,
        "room_to_freigrenze": round(room_to_freigrenze, 2),
        "current_crypto_short_gains": round(current_short_gains, 2),
        "current_crypto_short_losses": round(current_short_losses, 2),
        "current_crypto_net": round(current_net, 2),
        "holding_lots": holding_lots,
    }
