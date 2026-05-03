"""
``assets.views`` package — re-exports every view callable that
``assets/urls.py`` references via ``views.<name>``, so the URL config
keeps using the same flat namespace after the views were split into
per-domain submodules.

Add new view functions to the appropriate submodule and re-export them
here (and in ``__all__``) so ``urls.py`` can find them.
"""

from .alerts import alert_create, alert_delete, alerts_view
from .api import lookup_instrument_view, search_view
from .cash import cash_add_view, cash_delete_view, cash_edit_view, cash_list_view
from .crypto import (
    crypto_add_view,
    crypto_create_view,
    crypto_delete_view,
    crypto_detail_view,
    crypto_edit_view,
    crypto_list_redirect,
    crypto_list_view,
)
from .etf import (
    etf_add_view,
    etf_create_view,
    etf_delete_view,
    etf_detail_view,
    etf_edit_view,
    etf_list_redirect,
    etf_list_view,
    etf_master_edit_view,
    etf_plan_create_view,
    etf_plan_delete_view,
    etf_plan_edit_view,
    etf_plan_toggle_view,
)
from .holdings import holdings_view
from .reports import analytics_report_view, reports_index_view, tax_report_view
from .stock import (
    stock_add_view,
    stock_create_view,
    stock_delete_view,
    stock_detail_view,
    stock_edit_view,
    stock_list_redirect,
    stock_list_view,
)
from .transactions import transactions_view
from .watchlist import watchlist_toggle_view, watchlist_view

__all__ = [
    # alerts
    "alert_create",
    "alert_delete",
    "alerts_view",
    # api / search
    "lookup_instrument_view",
    "search_view",
    # cash
    "cash_add_view",
    "cash_delete_view",
    "cash_edit_view",
    "cash_list_view",
    # crypto
    "crypto_add_view",
    "crypto_create_view",
    "crypto_delete_view",
    "crypto_detail_view",
    "crypto_edit_view",
    "crypto_list_redirect",
    "crypto_list_view",
    # etf + savings plans
    "etf_add_view",
    "etf_create_view",
    "etf_delete_view",
    "etf_detail_view",
    "etf_edit_view",
    "etf_list_redirect",
    "etf_list_view",
    "etf_master_edit_view",
    "etf_plan_create_view",
    "etf_plan_delete_view",
    "etf_plan_edit_view",
    "etf_plan_toggle_view",
    # holdings + transactions
    "holdings_view",
    "transactions_view",
    # reports
    "analytics_report_view",
    "reports_index_view",
    "tax_report_view",
    # stock
    "stock_add_view",
    "stock_create_view",
    "stock_delete_view",
    "stock_detail_view",
    "stock_edit_view",
    "stock_list_redirect",
    "stock_list_view",
    # watchlist
    "watchlist_toggle_view",
    "watchlist_view",
]
