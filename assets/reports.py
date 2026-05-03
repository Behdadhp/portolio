"""
Report builders — pure data, view/PDF agnostic.

Two top-level entry points:

* ``build_tax_report(user, year=None, start=None, end=None)`` — produces a
  per-event ledger for stocks, ETFs, and crypto sells inside the chosen
  window, plus the German Freibetrag / Freigrenze tally that follows from
  the totals.

* ``build_analytics_report(user)`` — produces a portfolio-wide analytics
  snapshot (per-asset and aggregated by kind).

The tax functions reuse the same cost-basis math as
``services._compute_freibetrag_tax`` and ``services.compute_crypto_tax``
(weighted-average for stocks/ETFs, FIFO for crypto), but emit the per-sell
records that those aggregate functions discard. They also walk the full
transaction history before the period (so cost basis is correct) and only
EMIT events whose sell-date falls inside the requested window.
"""

from collections import defaultdict
from datetime import date as _date
from datetime import datetime
from typing import Optional

from django.core.cache import cache

from .models import CashFlow, Transaction
from .services import (
    compute_analytics,
    cost_basis_for,
    get_cash_summary,
    get_eur_usd_rate,
    get_total_portfolio_worth_usd,
)

# Mirror the constants used by services._compute_freibetrag_tax /
# services.compute_crypto_tax so a future change to one shows up in the
# other unambiguously.
FREIBETRAG_EUR = 1000.0   # Sparer-Pauschbetrag (capital gains, per year)
FREIGRENZE_EUR = 1000.0   # Crypto private-sale exemption limit (per year)
CAPITAL_GAINS_TAX_RATE = 0.26375  # 25% Kapitalertragsteuer + 5.5% Soli


# ── Per-asset-class event walkers ──────────────────────────────────────────


def _stock_etf_events(user, kind, start_date, end_date):
    """
    Per-sell records for stocks or ETFs whose sell-date is in
    ``[start_date, end_date]``. Uses weighted-average cost basis with
    fees baked in (buys add fee to cost basis; sells deduct fee from
    proceeds).

    Walks ALL transactions for each instrument, not just those in the
    window — otherwise cost basis at the point of an in-window sell
    would be wrong.
    """
    qs = Transaction.objects.filter(user=user, instrument__kind=kind)
    # NB: clear default ordering before .distinct(). Transaction.Meta.ordering
    # (date desc, created_at desc) leaks into the SELECT DISTINCT clause and
    # produces duplicate instrument_ids — same bug previously masked in
    # services._compute_freibetrag_tax / compute_crypto_tax.
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    events = []
    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        name = None
        cost_basis = 0.0
        units = 0.0

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
                name = tx.instrument.name
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                cost_basis += amt * px + fee
                units += amt
            elif tx.status == "sold" and units > 0:
                avg = cost_basis / units
                proceeds = amt * px - fee
                cost = amt * avg
                pnl = proceeds - cost
                cost_basis -= cost
                units -= amt

                if start_date <= tx.date <= end_date:
                    events.append({
                        "date": tx.date,
                        "symbol": symbol,
                        "name": name,
                        "amount": amt,
                        "sell_price": round(px, 4),
                        "avg_cost": round(avg, 4),
                        "fee": round(fee, 2),
                        "proceeds": round(proceeds, 2),
                        "cost": round(cost, 2),
                        "pnl": round(pnl, 2),
                    })

    events.sort(key=lambda e: (e["date"], e["symbol"]))
    return events


def _crypto_events(user, start_date, end_date):
    """
    Per-sell-lot records for crypto whose sell-date is in
    ``[start_date, end_date]``. FIFO-matched: each sell is split across
    however many oldest unsold buy lots it consumes, and each split lot
    becomes its own event row with its own holding-period classification.

    Buy fees are baked into the lot's effective per-unit price; sell fees
    are prorated across the consumed lots.
    """
    qs = Transaction.objects.filter(user=user, instrument__kind="crypto")
    # NB: clear default ordering before .distinct(). Transaction.Meta.ordering
    # (date desc, created_at desc) leaks into the SELECT DISTINCT clause and
    # produces duplicate instrument_ids — same bug previously masked in
    # services._compute_freibetrag_tax / compute_crypto_tax.
    instrument_ids = qs.order_by().values_list("instrument_id", flat=True).distinct()

    events = []
    for inst_id in instrument_ids:
        txs = (
            qs.filter(instrument_id=inst_id)
            .select_related("instrument")
            .order_by("date", "status", "pk")
        )
        symbol = None
        name = None
        lots = []

        for tx in txs:
            if symbol is None:
                symbol = tx.instrument.symbol
                name = tx.instrument.name
            amt = float(tx.amount)
            px = float(tx.price)
            fee = float(tx.fee or 0)

            if tx.status == "bought":
                effective_price = px + (fee / amt if amt > 0 else 0)
                lots.append({
                    "date": tx.date,
                    "amount": amt,
                    "price": effective_price,
                })
            elif tx.status == "sold":
                fee_per_unit = (fee / amt) if amt > 0 else 0
                remaining = amt
                while remaining > 0 and lots:
                    lot = lots[0]
                    sell_from_lot = min(remaining, lot["amount"])
                    holding_days = (tx.date - lot["date"]).days
                    proceeds = sell_from_lot * px - fee_per_unit * sell_from_lot
                    cost = sell_from_lot * lot["price"]
                    pnl = proceeds - cost

                    if start_date <= tx.date <= end_date:
                        events.append({
                            "date": tx.date,
                            "symbol": symbol,
                            "name": name,
                            "amount": sell_from_lot,
                            "sell_price": round(px, 4),
                            "lot_buy_date": lot["date"],
                            "lot_price": round(lot["price"], 4),
                            "holding_days": holding_days,
                            "is_long_term": holding_days > 365,
                            "fee": round(fee_per_unit * sell_from_lot, 4),
                            "proceeds": round(proceeds, 2),
                            "cost": round(cost, 2),
                            "pnl": round(pnl, 2),
                        })

                    lot["amount"] -= sell_from_lot
                    remaining -= sell_from_lot
                    if lot["amount"] <= 0.0001:
                        lots.pop(0)

    events.sort(key=lambda e: (e["date"], e["symbol"], e["lot_buy_date"]))
    return events


# ── Aggregators ────────────────────────────────────────────────────────────


def _aggregate_freibetrag(events):
    """For stocks/ETFs. Adds a `running_total` column and class totals."""
    gains = sum(e["pnl"] for e in events if e["pnl"] > 0)
    losses = sum(-e["pnl"] for e in events if e["pnl"] < 0)
    net = gains - losses
    running = 0.0
    enriched = []
    for e in events:
        running += e["pnl"]
        enriched.append({**e, "running_total": round(running, 2)})
    return {
        "events": enriched,
        "gains": round(gains, 2),
        "losses": round(losses, 2),
        "net": round(net, 2),
        "count": len(events),
    }


def _aggregate_crypto(events):
    """
    Crypto needs short- vs long-term split: long-term lots (>365 d) are
    fully tax-free in Germany and are excluded from the Freigrenze test.
    Running total only counts short-term P&L.
    """
    st_gains = sum(e["pnl"] for e in events if not e["is_long_term"] and e["pnl"] > 0)
    st_losses = sum(
        -e["pnl"] for e in events if not e["is_long_term"] and e["pnl"] < 0
    )
    st_net = st_gains - st_losses
    lt_gains = sum(e["pnl"] for e in events if e["is_long_term"] and e["pnl"] > 0)
    lt_losses = sum(-e["pnl"] for e in events if e["is_long_term"] and e["pnl"] < 0)

    running = 0.0
    enriched = []
    for e in events:
        if not e["is_long_term"]:
            running += e["pnl"]
        enriched.append({**e, "short_term_running": round(running, 2)})
    return {
        "events": enriched,
        "short_term_gains": round(st_gains, 2),
        "short_term_losses": round(st_losses, 2),
        "short_term_net": round(st_net, 2),
        "long_term_gains": round(lt_gains, 2),
        "long_term_losses": round(lt_losses, 2),
        "count": len(events),
    }


# ── Public entry points ────────────────────────────────────────────────────


def build_tax_report(
    user,
    year: Optional[int] = None,
    start: Optional[_date] = None,
    end: Optional[_date] = None,
):
    """
    Build a complete tax report dict for the given period.

    Pass either ``year`` (full calendar year) OR both ``start`` and
    ``end`` (inclusive custom range). The Freibetrag/Freigrenze
    calculations are only meaningful for a full calendar year, so when
    a custom range is supplied that doesn't span exactly Jan 1 → Dec 31
    of one year, the tax-owed numbers are returned as ``None`` and the
    UI/PDF should show events + totals only.
    """
    if year is not None:
        start_date = _date(year, 1, 1)
        end_date = _date(year, 12, 31)
        period_label = f"Tax Year {year}"
        is_full_year = True
        full_year = year
    else:
        if start is None or end is None:
            raise ValueError("Pass either year or both start and end")
        if end < start:
            raise ValueError("end date is before start date")
        start_date = start
        end_date = end
        is_full_year = (
            start.month == 1 and start.day == 1
            and end.month == 12 and end.day == 31
            and start.year == end.year
        )
        full_year = start.year if is_full_year else None
        period_label = (
            f"Tax Year {start.year}" if is_full_year
            else f"{start_date.isoformat()} → {end_date.isoformat()}"
        )

    eur_usd = get_eur_usd_rate() or 1.0
    freibetrag_usd = round(FREIBETRAG_EUR * eur_usd, 2)
    freigrenze_usd = round(FREIGRENZE_EUR * eur_usd, 2)

    stocks = _aggregate_freibetrag(_stock_etf_events(user, "stock", start_date, end_date))
    etfs = _aggregate_freibetrag(_stock_etf_events(user, "etf", start_date, end_date))
    crypto = _aggregate_crypto(_crypto_events(user, start_date, end_date))

    # Capital-gains side: stocks + ETFs share the Freibetrag (same income
    # class — Kapitalerträge), losses offset gains within the class.
    capital_gains_gains = stocks["gains"] + etfs["gains"]
    capital_gains_losses = stocks["losses"] + etfs["losses"]
    capital_gains_net = capital_gains_gains - capital_gains_losses

    if is_full_year:
        freibetrag_used = max(0.0, min(capital_gains_net, freibetrag_usd))
        freibetrag_remaining = round(freibetrag_usd - freibetrag_used, 2)
        taxable_capital = max(0.0, capital_gains_net - freibetrag_usd)
        estimated_tax = taxable_capital * CAPITAL_GAINS_TAX_RATE
        net_after_tax = capital_gains_net - estimated_tax

        crypto_st_net = crypto["short_term_net"]
        crypto_exceeds = crypto_st_net >= freigrenze_usd
        # NB Freigrenze (not Freibetrag): if exceeded, the WHOLE net is
        # taxable at the user's personal income-tax rate (not the 26.375%).
        crypto_taxable = crypto_st_net if crypto_exceeds else 0.0
    else:
        freibetrag_used = None
        freibetrag_remaining = None
        taxable_capital = None
        estimated_tax = None
        net_after_tax = None
        crypto_exceeds = None
        crypto_taxable = None

    return {
        "user": user,
        "generated_at": datetime.now(),
        "eur_usd_rate": round(eur_usd, 4),

        "period_label": period_label,
        "start_date": start_date,
        "end_date": end_date,
        "year": full_year,
        "is_full_year": is_full_year,

        "freibetrag": freibetrag_usd,
        "freigrenze": freigrenze_usd,
        "tax_rate": CAPITAL_GAINS_TAX_RATE,
        "tax_rate_pct": round(CAPITAL_GAINS_TAX_RATE * 100, 3),

        "stocks": stocks,
        "etfs": etfs,
        "crypto": crypto,

        # Capital-gains rollup (stocks + ETFs combined for Freibetrag)
        "capital_gains_gains": round(capital_gains_gains, 2),
        "capital_gains_losses": round(capital_gains_losses, 2),
        "capital_gains_net": round(capital_gains_net, 2),
        "freibetrag_used": (
            round(freibetrag_used, 2) if freibetrag_used is not None else None
        ),
        "freibetrag_remaining": freibetrag_remaining,
        "taxable_capital": (
            round(taxable_capital, 2) if taxable_capital is not None else None
        ),
        "estimated_tax": (
            round(estimated_tax, 2) if estimated_tax is not None else None
        ),
        "net_after_tax": (
            round(net_after_tax, 2) if net_after_tax is not None else None
        ),

        # Crypto rollup
        "crypto_exceeds_freigrenze": crypto_exceeds,
        "crypto_taxable_short_term": (
            round(crypto_taxable, 2) if crypto_taxable is not None else None
        ),
    }


def build_analytics_report(user):
    """
    Portfolio-wide analytics snapshot for the current moment.

    Reuses ``services.compute_analytics`` per-asset and adds per-kind
    aggregates plus overall portfolio metrics (cash, worth, real P&L).
    """
    qs_all = Transaction.objects.filter(user=user).select_related("instrument")
    seen = {}
    for tx in qs_all:
        key = (tx.instrument.kind, tx.instrument.symbol, tx.instrument.name)
        seen[key] = True

    rows = []
    for (kind, symbol, name) in seen:
        sub_qs = qs_all.filter(instrument__symbol=symbol)
        a = compute_analytics(sub_qs, symbol)
        rows.append({
            "kind": kind,
            "symbol": symbol,
            "name": name,
            "analytics": a,
        })

    rows.sort(key=lambda r: (r["kind"], r["symbol"]))

    # Per-kind aggregates. Note: a row with `warning` (sold-out / oversold)
    # has fewer keys, so use .get() with defaults.
    summary = {}
    for kind in ("stock", "etf", "crypto"):
        kind_rows = [r for r in rows if r["kind"] == kind]
        invested = 0.0
        sold = 0.0
        realized = 0.0
        cost_basis = 0.0
        current_value = 0.0
        held_assets = 0
        for r in kind_rows:
            a = r["analytics"] or {}
            invested += float(a.get("total_invested") or 0)
            sold += float(a.get("total_sold_value") or 0)
            realized += float(a.get("realized_pnl") or 0)
            cost_basis += float(a.get("cost_basis") or 0)
            current_value += float(a.get("current_value") or 0)
            if (a.get("units") or 0) > 0 and not a.get("warning"):
                held_assets += 1
        unrealized = current_value - cost_basis if current_value > 0 else 0.0
        summary[kind] = {
            "invested": round(invested, 2),
            "sold": round(sold, 2),
            "realized_pnl": round(realized, 2),
            "cost_basis": round(cost_basis, 2),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "asset_count": len(kind_rows),
            "currently_held": held_assets,
        }

    cash_summary = get_cash_summary(user)
    portfolio_worth = get_total_portfolio_worth_usd(user)
    real_pnl = round(portfolio_worth - cash_summary["net_invested_usd"], 2)
    real_pnl_pct = (
        round(real_pnl / cash_summary["net_invested_usd"] * 100, 2)
        if cash_summary["net_invested_usd"] > 0 else 0.0
    )

    return {
        "user": user,
        "generated_at": datetime.now(),
        "eur_usd_rate": round(get_eur_usd_rate() or 1.0, 4),
        "rows": rows,
        "summary": summary,
        "cash_summary": cash_summary,
        "portfolio_worth": round(portfolio_worth, 2),
        "real_pnl": real_pnl,
        "real_pnl_pct": real_pnl_pct,
    }


def available_tax_years(user):
    """
    Distinct years the user has at least one sell transaction in. Used
    to populate the year dropdown on the Reports landing page.
    """
    years = (
        Transaction.objects.filter(user=user, status="sold")
        .dates("date", "year", order="DESC")
    )
    return [d.year for d in years]
