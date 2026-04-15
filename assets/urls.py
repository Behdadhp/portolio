from django.urls import path
from . import views

urlpatterns = [
    path("stocks/", views.stock_list_view, name="stocks"),
    path("stocks/add/", views.stock_add_view, name="stock_add"),
    path("stocks/add/<str:symbol>/", views.stock_add_view, name="stock_add_for"),
    path("stocks/edit/<uuid:pk>/", views.stock_edit_view, name="stock_edit"),
    path("stocks/delete/<uuid:pk>/", views.stock_delete_view, name="stock_delete"),
    path("stocks/<str:symbol>/", views.stock_detail_view, name="stock_detail"),
    path("crypto/", views.crypto_list_view, name="crypto"),
    path("crypto/add/", views.crypto_add_view, name="crypto_add"),
    path("crypto/add/<str:symbol>/", views.crypto_add_view, name="crypto_add_for"),
    path("crypto/edit/<uuid:pk>/", views.crypto_edit_view, name="crypto_edit"),
    path("crypto/delete/<uuid:pk>/", views.crypto_delete_view, name="crypto_delete"),
    path("crypto/<str:symbol>/", views.crypto_detail_view, name="crypto_detail"),
]
