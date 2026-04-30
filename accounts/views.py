from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ChangePasswordForm, EditProfileForm, LoginForm, RegisterForm
from .models import User


def home_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "accounts/home.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = LoginForm()
    error = None

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                return redirect("dashboard")
            else:
                error = "Email or password is wrong."

    return render(request, "accounts/login.html", {"form": form, "error": error})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm()

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                birthdate=form.cleaned_data["birthdate"],
            )
            login(request, user)
            return redirect("dashboard")

    return render(request, "accounts/register.html", {"form": form})


@login_required
def dashboard_view(request):
    import json
    from django.core.cache import cache
    from assets.models import CashFlow, PriceAlert, Transaction
    from assets.services import (
        get_cash_summary,
        get_portfolio_history,
        get_total_portfolio_worth_usd,
    )

    # Build the holdings & cost-basis maps the WS-driven hero needs.
    # We don't render an allocation card on the dashboard anymore — that lives
    # on /holdings/ — so we just need enough state for the live P&L number.
    holdings = {}
    cost_bases = {}  # {symbol: cost_basis} for live P&L

    for tx in Transaction.objects.filter(user=request.user).select_related("instrument"):
        sym = tx.instrument.symbol
        amt = float(tx.amount) if tx.status == "bought" else -float(tx.amount)
        holdings[sym] = holdings.get(sym, 0.0) + amt

    # Cost basis per symbol (weighted-average across all the user's txs).
    from assets.services import cost_basis_for

    for sym in [s for s, qty in holdings.items() if qty > 0]:
        cost_bases[sym] = cost_basis_for(
            Transaction.objects.filter(user=request.user, instrument__symbol=sym)
        )

    # Top 5 nearest active alerts (by % distance to target if we have a price).
    all_active = list(
        PriceAlert.objects.filter(user=request.user, email_sent=False)
        .select_related("instrument")
    )
    def _alert_distance(a):
        live = cache.get(f"finnhub_{a.instrument.symbol}")
        if live is None or not a.target_price:
            return float("inf")
        return abs(float(live) - float(a.target_price)) / float(a.target_price)
    all_active.sort(key=_alert_distance)
    active_alerts = all_active[:5]

    # Recent activity: last 5 asset transactions + last 5 cash flows, merged.
    recent_tx = list(
        Transaction.objects.filter(user=request.user)
        .select_related("instrument").order_by("-date", "-created_at")[:5]
    )
    recent_cash = list(CashFlow.objects.filter(user=request.user).order_by("-date", "-created_at")[:5])
    recent_activity = []
    for t in recent_tx:
        recent_activity.append({
            "type": "asset",
            "date": t.date,
            "kind": t.instrument.kind,
            "symbol": t.instrument.symbol,
            "name": t.instrument.name,
            "action": t.status,
            "amount": float(t.amount),
            "price": float(t.price),
            "value_usd": round(float(t.amount) * float(t.price), 2),
        })
    for c in recent_cash:
        recent_activity.append({
            "type": "cash",
            "date": c.date,
            "action": c.direction,
            "amount_usd": float(c.amount_usd),
            "note": c.note,
        })
    recent_activity.sort(key=lambda r: r["date"], reverse=True)
    recent_activity = recent_activity[:7]

    cash_summary = get_cash_summary(request.user)
    portfolio_worth = get_total_portfolio_worth_usd(request.user)
    real_pnl = round(portfolio_worth - cash_summary["net_invested_usd"], 2)
    real_pnl_pct = (
        round(real_pnl / cash_summary["net_invested_usd"] * 100, 2)
        if cash_summary["net_invested_usd"] > 0
        else 0.0
    )

    history = get_portfolio_history(request.user)

    return render(
        request,
        "accounts/dashboard.html",
        {
            "holdings_json": json.dumps(holdings),
            "cost_bases_json": json.dumps(cost_bases),
            "history_json": json.dumps(history),
            "active_alerts": active_alerts,
            "recent_activity": recent_activity,
            "cash_summary": cash_summary,
            "portfolio_worth": portfolio_worth,
            "real_pnl": real_pnl,
            "real_pnl_pct": real_pnl_pct,
        },
    )


@login_required
def edit_profile_view(request):
    profile_form = EditProfileForm(instance=request.user)
    password_form = ChangePasswordForm(user=request.user)

    if request.method == "POST":
        if "save_profile" in request.POST:
            profile_form = EditProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("edit_profile")

        elif "change_password" in request.POST:
            password_form = ChangePasswordForm(request.POST, user=request.user)
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data["new_password"])
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed successfully.")
                return redirect("edit_profile")

    return render(
        request,
        "accounts/edit_profile.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


@login_required
def market_view(request):
    from assets.models import WatchlistEntry
    from assets.services import load_live_prices

    watchlist_ids = set(
        WatchlistEntry.objects.filter(user=request.user).values_list(
            "instrument_id", flat=True
        )
    )

    return render(
        request,
        "accounts/market.html",
        {
            "stock_prices": load_live_prices("stock", watchlist_ids),
            "crypto_prices": load_live_prices("crypto", watchlist_ids),
        },
    )


def logout_view(request):
    logout(request)
    return redirect("home")
