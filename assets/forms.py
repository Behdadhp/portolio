from django import forms
from .models import ETF, CryptoAsset, ETFAsset, ETFSavingsPlan, StockAsset

# Symbols that would shadow ETF URL routes (urls.py).
RESERVED_ETF_SYMBOLS = {"new", "add", "edit", "delete", "plans", "master"}


class ETFForm(forms.ModelForm):
    class Meta:
        model = ETF
        fields = ["name", "symbol", "last_price"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "symbol": forms.TextInput(attrs={"class": "form-control"}),
            "last_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
        }

    def clean_symbol(self):
        symbol = self.cleaned_data["symbol"].strip()
        if symbol.lower() in RESERVED_ETF_SYMBOLS:
            raise forms.ValidationError(
                f"'{symbol}' is reserved and cannot be used as an ETF symbol."
            )
        return symbol


class CryptoAssetForm(forms.ModelForm):
    class Meta:
        model = CryptoAsset
        fields = ["crypto", "price", "amount", "date", "status"]
        widgets = {
            "crypto": forms.Select(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00000001"}
            ),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }


class StockAssetForm(forms.ModelForm):
    class Meta:
        model = StockAsset
        fields = ["stock", "price", "amount", "date", "status"]
        widgets = {
            "stock": forms.Select(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00000001"}
            ),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }


class ETFAssetForm(forms.ModelForm):
    class Meta:
        model = ETFAsset
        fields = ["etf", "price", "amount", "date", "status"]
        widgets = {
            "etf": forms.Select(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00000001"}
            ),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }


class ETFSavingsPlanForm(forms.ModelForm):
    class Meta:
        model = ETFSavingsPlan
        fields = ["etf", "amount", "currency", "interval", "start_date", "active"]
        widgets = {
            "etf": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "currency": forms.HiddenInput(),
            "interval": forms.Select(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount
