from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("kayit/", views.signup, name="signup"),
    path("giris/", views.SignInView.as_view(), name="login"),
    path("cikis/", views.SignOutView.as_view(), name="logout"),
]
