from django.urls import path
from . import views

urlpatterns = [
    path("stocks/", views.stock_list_view, name="stocks"),
    path("stocks/add/", views.stock_add_view, name="stock_add"),
    path("stocks/add/<str:symbol>/", views.stock_add_view, name="stock_add_for"),
    path("stocks/edit/<uuid:pk>/", views.stock_edit_view, name="stock_edit"),
    path("stocks/delete/<uuid:pk>/", views.stock_delete_view, name="stock_delete"),
    path("stocks/<str:symbol>/", views.stock_detail_view, name="stock_detail"),
    path("etfs/", views.etf_list_view, name="etfs"),
    path("etfs/new/", views.etf_create_view, name="etf_create"),
    path(
        "etfs/master/edit/<str:symbol>/",
        views.etf_master_edit_view,
        name="etf_master_edit",
    ),
    path("etfs/add/", views.etf_add_view, name="etf_add"),
    path("etfs/add/<str:symbol>/", views.etf_add_view, name="etf_add_for"),
    path("etfs/edit/<uuid:pk>/", views.etf_edit_view, name="etf_edit"),
    path("etfs/delete/<uuid:pk>/", views.etf_delete_view, name="etf_delete"),
    path("etfs/plans/create/", views.etf_plan_create_view, name="etf_plan_create"),
    path(
        "etfs/plans/create/<str:symbol>/",
        views.etf_plan_create_view,
        name="etf_plan_create_for",
    ),
    path("etfs/plans/edit/<uuid:pk>/", views.etf_plan_edit_view, name="etf_plan_edit"),
    path(
        "etfs/plans/toggle/<uuid:pk>/",
        views.etf_plan_toggle_view,
        name="etf_plan_toggle",
    ),
    path(
        "etfs/plans/delete/<uuid:pk>/",
        views.etf_plan_delete_view,
        name="etf_plan_delete",
    ),
    path("etfs/<str:symbol>/", views.etf_detail_view, name="etf_detail"),
    path("crypto/", views.crypto_list_view, name="crypto"),
    path("crypto/add/", views.crypto_add_view, name="crypto_add"),
    path("crypto/add/<str:symbol>/", views.crypto_add_view, name="crypto_add_for"),
    path("crypto/edit/<uuid:pk>/", views.crypto_edit_view, name="crypto_edit"),
    path("crypto/delete/<uuid:pk>/", views.crypto_delete_view, name="crypto_delete"),
    path("crypto/<str:symbol>/", views.crypto_detail_view, name="crypto_detail"),
    # Cash flow
    path("cash/", views.cash_list_view, name="cash"),
    path("cash/add/", views.cash_add_view, name="cash_add"),
    path("cash/edit/<uuid:pk>/", views.cash_edit_view, name="cash_edit"),
    path("cash/delete/<uuid:pk>/", views.cash_delete_view, name="cash_delete"),
    # Price Alert API
    path("api/alerts/create/", views.alert_create, name="alert_create"),
    path("api/alerts/<uuid:pk>/delete/", views.alert_delete, name="alert_delete"),
]
