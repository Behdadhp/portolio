from rest_framework import serializers
from .models import Crypto, CryptoAsset, Stock, StockAsset


class CryptoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crypto
        fields = ["id", "name", "symbol"]


class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = ["id", "name", "symbol"]


class CryptoAssetSerializer(serializers.ModelSerializer):
    crypto = CryptoSerializer(read_only=True)

    class Meta:
        model = CryptoAsset
        fields = ["id", "crypto", "price", "amount", "date", "status"]


class StockAssetSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)

    class Meta:
        model = StockAsset
        fields = ["id", "stock", "price", "amount", "date", "status"]
