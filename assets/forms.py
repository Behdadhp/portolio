from django import forms
from .models import CryptoAsset, StockAsset


class CryptoAssetForm(forms.ModelForm):
    class Meta:
        model = CryptoAsset
        fields = ["crypto", "price", "amount", "date", "status"]
        widgets = {
            "crypto": forms.Select(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.00000001"}),
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
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.00000001"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }
