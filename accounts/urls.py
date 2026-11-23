from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("kayit/", views.signup, name="signup"),
    path("giris/", views.SignInView.as_view(), name="login"),
    path("cikis/", views.SignOutView.as_view(), name="logout"),
    path("parola-sifirla/", views.PasswordResetRequestView.as_view(), name="password_reset"),
    path("parola-sifirla/gonderildi/", views.PasswordResetSentView.as_view(), name="password_reset_done"),
    path("parola-sifirla/tamam/", views.PasswordResetFinishedView.as_view(), name="password_reset_complete"),
    path(
        "parola-sifirla/<uidb64>/<token>/",
        views.PasswordResetNewPasswordView.as_view(),
        name="password_reset_confirm",
    ),
]
