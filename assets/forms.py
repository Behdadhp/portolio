from django import forms

from .models import CashFlow, ETFSavingsPlan, Instrument, Transaction


class CashFlowForm(forms.ModelForm):
    class Meta:
        model = CashFlow
        fields = ["amount_usd", "direction", "date", "note"]
        widgets = {
            "amount_usd": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "direction": forms.Select(attrs={"class": "form-control"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "note": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_amount_usd(self):
        amount = self.cleaned_data["amount_usd"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


# Symbols that would shadow ETF URL routes (urls.py).
RESERVED_ETF_SYMBOLS = {"new", "add", "edit", "delete", "plans", "master"}


class ETFForm(forms.ModelForm):
    """Master-record form for ETFs (single-kind subset of Instrument)."""

    class Meta:
        model = Instrument
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

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.kind = Instrument.Kind.ETF
        if commit:
            instance.save()
        return instance


class _TransactionFormBase(forms.ModelForm):
    """
    Shared base for per-kind transaction forms. Subclasses set `kind` and
    rename the `instrument` field for legacy template/POST compatibility.
    """

    kind = None  # Set by subclass to one of Instrument.Kind values.
    instrument_field_name = "instrument"

    class Meta:
        model = Transaction
        fields = ["instrument", "price", "amount", "date", "status"]
        widgets = {
            "price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00000001"}
            ),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restrict the instrument dropdown to this kind, and rename the field
        # so the POST/initial keys remain `stock` / `crypto` / `etf`.
        old_field = self.fields.pop("instrument")
        old_field.queryset = Instrument.objects.filter(kind=self.kind)
        old_field.widget = forms.Select(attrs={"class": "form-control"})
        self.fields[self.instrument_field_name] = old_field

    def _post_clean(self):
        # Map the renamed field back onto the model's `instrument` attribute
        # before ModelForm validation runs full_clean on the instance.
        if self.instrument_field_name != "instrument":
            data = self.cleaned_data
            if self.instrument_field_name in data:
                data["instrument"] = data[self.instrument_field_name]
        super()._post_clean()


class StockAssetForm(_TransactionFormBase):
    kind = Instrument.Kind.STOCK
    instrument_field_name = "stock"


class CryptoAssetForm(_TransactionFormBase):
    kind = Instrument.Kind.CRYPTO
    instrument_field_name = "crypto"


class ETFAssetForm(_TransactionFormBase):
    kind = Instrument.Kind.ETF
    instrument_field_name = "etf"


class ETFSavingsPlanForm(forms.ModelForm):
    class Meta:
        model = ETFSavingsPlan
        fields = ["instrument", "amount", "currency", "interval", "start_date", "active"]
        widgets = {
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "currency": forms.HiddenInput(),
            "interval": forms.Select(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the form field name as `etf` for template/POST compatibility,
        # but restrict the queryset to ETF-kind instruments.
        old_field = self.fields.pop("instrument")
        old_field.queryset = Instrument.objects.filter(kind=Instrument.Kind.ETF)
        old_field.widget = forms.Select(attrs={"class": "form-control"})
        self.fields["etf"] = old_field

    def _post_clean(self):
        data = self.cleaned_data
        if "etf" in data:
            data["instrument"] = data["etf"]
        super()._post_clean()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount
