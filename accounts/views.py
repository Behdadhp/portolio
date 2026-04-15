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
    from assets.models import Crypto, CryptoAsset, Stock, StockAsset
    from assets.services import get_asset_summary, load_live_prices

    stock_summary = list(get_asset_summary(
        StockAsset.objects.filter(user=request.user), "stock__name", "stock__symbol"
    ))
    crypto_summary = list(get_asset_summary(
        CryptoAsset.objects.filter(user=request.user), "crypto__name", "crypto__symbol"
    ))

    holdings = {}
    allocation = []  # [{label, symbol, value, type}]

    for row in stock_summary:
        amt = float(row["total"])
        holdings[row["symbol"]] = amt
        price = cache.get(f"finnhub_{row['symbol']}")
        worth = round(amt * float(price), 2) if price is not None and amt > 0 else 0
        allocation.append({
            "label": row["name"],
            "symbol": row["symbol"],
            "value": worth,
            "type": "stock",
        })

    for row in crypto_summary:
        amt = float(row["total"])
        holdings[row["symbol"]] = amt
        price = cache.get(f"finnhub_{row['symbol']}")
        worth = round(amt * float(price), 2) if price is not None and amt > 0 else 0
        allocation.append({
            "label": row["name"],
            "symbol": row["symbol"],
            "value": worth,
            "type": "crypto",
        })

    return render(request, "accounts/dashboard.html", {
        "stock_prices": load_live_prices(Stock),
        "crypto_prices": load_live_prices(Crypto),
        "holdings_json": json.dumps(holdings),
        "allocation_json": json.dumps(allocation),
    })


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


def logout_view(request):
    logout(request)
    return redirect("home")
