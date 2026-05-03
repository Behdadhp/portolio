"""
ETF savings-plan execution. ``execute_due_savings_plans`` is the
idempotent worker called from the Celery price-stream loop; it catches
up any missed days, posts a Transaction at the plan's stored rate
(falling back to last_price/0 when the price is unavailable), and
advances the next-execution cursor by interval.
"""

import logging
from decimal import Decimal

from .prices import get_eur_usd_rate

logger = logging.getLogger(__name__)


def advance_savings_plan_date(plan, current):
    """
    Compute the next execution date for a savings plan after `current`.

    Monthly/quarterly anchor to the original `start_date.day`, clamped to
    month-end (so a 31st plan falls on Feb 28/29, March 31, April 30, etc.).
    """
    import calendar
    from datetime import date, timedelta

    interval = plan.interval
    if interval == "weekly":
        return current + timedelta(days=7)
    if interval == "biweekly":
        return current + timedelta(days=14)

    months = {"monthly": 1, "quarterly": 3}.get(interval, 1)
    target_year = current.year + (current.month - 1 + months) // 12
    target_month = (current.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    target_day = min(plan.start_date.day, last_day)
    return date(target_year, target_month, target_day)


def execute_due_savings_plans():
    """
    Run all active ETFSavingsPlans whose next_execution_date <= today.

    For each due plan:
      - Loop while still due (catches up missed days).
      - Use the ETF's last_price (which mirrors the price cache).
        If unavailable, create the transaction with price=0 and amount=0
        so the user can fill it in manually later.
      - Insert a Transaction row dated `next_execution_date`.
      - Advance next_execution_date by interval, anchored to start_date.day.

    Idempotent: safe to call repeatedly; each plan only executes when due.
    """
    from datetime import date

    from django.utils import timezone

    from ..models import ETFSavingsPlan, Transaction

    today = date.today()
    due = ETFSavingsPlan.objects.filter(
        active=True, next_execution_date__lte=today
    ).select_related("instrument", "user")

    executed = 0
    for plan in due:
        while plan.active and plan.next_execution_date <= today:
            if plan.currency == "EUR":
                fx = get_eur_usd_rate()
                if fx is None:
                    logger.warning(
                        "Skipping EUR savings plan %s: EUR/USD rate unavailable",
                        plan.id,
                    )
                    break
                usd_spend = float(plan.amount) * fx
            else:
                usd_spend = float(plan.amount)

            last_price = plan.instrument.last_price
            if last_price is not None and float(last_price) > 0:
                price_val = float(last_price)
                amount_val = usd_spend / price_val
            else:
                price_val = 0.0
                amount_val = 0.0

            Transaction.objects.create(
                user=plan.user,
                instrument=plan.instrument,
                price=Decimal(str(round(price_val, 2))),
                amount=Decimal(str(round(amount_val, 8))),
                date=plan.next_execution_date,
                status="bought",
            )

            plan.last_executed_at = timezone.now()
            plan.next_execution_date = advance_savings_plan_date(
                plan, plan.next_execution_date
            )
            plan.save(update_fields=["last_executed_at", "next_execution_date"])
            executed += 1

    if executed:
        logger.info("Executed %d ETF savings plan transaction(s)", executed)
    return executed
