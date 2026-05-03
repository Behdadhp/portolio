"""
``assets.services`` package — re-exports every public name that callers
expect on the flat ``assets.services`` namespace, so existing imports
like ``from assets.services import compute_analytics`` keep working
after the split into submodules.

If you add a new symbol in a submodule, also add it here (and to
``__all__``) so it's discoverable from the package root.
"""

from .alerts import sync_alert_cache
from .analytics import compute_analytics, cost_basis_for
from .cash import get_cash_summary, get_total_portfolio_worth_usd
from .helpers import (
    ALLOWED_PER_PAGE,
    DEFAULT_PER_PAGE,
    DETAIL_COLUMNS,
    DETAIL_SORT_FIELDS,
    apply_filters,
    get_asset_summary,
    get_filter_ranges,
    sort_and_paginate,
)
from .history import get_portfolio_history
from .prices import (
    backfill_coingecko_crypto,
    backfill_finnhub_stock_candles,
    get_eur_usd_rate,
    load_live_prices,
    lookup_instrument,
    refresh_instrument_last_price,
    run_price_snapshot_catchup,
    snapshot_today_from_cache,
)
from .savings_plans import advance_savings_plan_date, execute_due_savings_plans
from .tax_crypto import compute_crypto_tax
from .tax_freibetrag import compute_etf_tax, compute_stock_tax

__all__ = [
    # helpers
    "ALLOWED_PER_PAGE",
    "DEFAULT_PER_PAGE",
    "DETAIL_COLUMNS",
    "DETAIL_SORT_FIELDS",
    "apply_filters",
    "get_asset_summary",
    "get_filter_ranges",
    "sort_and_paginate",
    # analytics
    "compute_analytics",
    "cost_basis_for",
    # cash
    "get_cash_summary",
    "get_total_portfolio_worth_usd",
    # tax
    "compute_crypto_tax",
    "compute_etf_tax",
    "compute_stock_tax",
    # prices
    "backfill_coingecko_crypto",
    "backfill_finnhub_stock_candles",
    "get_eur_usd_rate",
    "load_live_prices",
    "lookup_instrument",
    "refresh_instrument_last_price",
    "run_price_snapshot_catchup",
    "snapshot_today_from_cache",
    # history
    "get_portfolio_history",
    # savings plans
    "advance_savings_plan_date",
    "execute_due_savings_plans",
    # alerts
    "sync_alert_cache",
]
