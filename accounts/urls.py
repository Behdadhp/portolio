from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("profile/edit/", views.edit_profile_view, name="edit_profile"),
    path("logout/", views.logout_view, name="logout"),
]
