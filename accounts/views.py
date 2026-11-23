from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from . import ratelimit
from .forms import LoginForm, SignUpForm


def _safe_next(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return ""


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    next_url = _safe_next(request)
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ip_key = ratelimit.request_digest(request)
        wait = ratelimit.check("signup", ip_key)
        if wait:
            form.add_error(
                None, f"Bu ağdan kısa sürede çok sayıda hesap açıldı. {ratelimit.human_wait(wait)} sonra tekrar dene."
            )
            response = render(request, "accounts/signup.html", {"form": form, "next": next_url}, status=429)
            response["Retry-After"] = str(wait)
            return response
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            # Someone took the email/username between validation and save.
            form.add_error(None, "Bu e-posta veya kullanıcı adı az önce alındı. Lütfen başka birini dene.")
        else:
            ratelimit.record("signup", ip_key)
            login(request, user)
            messages.success(request, f"Hoş geldin, @{user.username}!")
            return redirect(next_url or settings.LOGIN_REDIRECT_URL)

    return render(request, "accounts/signup.html", {"form": form, "next": next_url})


class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class SignOutView(LogoutView):
    """Django's LogoutView only accepts POST."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "Çıkış yaptın. Görüşmek üzere!")
        return response
