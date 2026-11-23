from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from . import ratelimit
from .forms import LoginForm, PasswordResetRequestForm, SetNewPasswordForm, SignUpForm


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Read at request time so the link only shows while the feature is actually available.
        context["password_reset_enabled"] = settings.PASSWORD_RESET_ENABLED
        return context


class SignOutView(LogoutView):
    """Django's LogoutView only accepts POST."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "Çıkış yaptın. Görüşmek üzere!")
        return response


# --- Password reset ----------------------------------------------------------

class PasswordResetFeatureMixin:
    """The whole flow answers 404 unless e-mail is configured (see PASSWORD_RESET_ENABLED)."""

    def dispatch(self, request, *args, **kwargs):
        if not settings.PASSWORD_RESET_ENABLED:
            raise Http404("Parola sıfırlama şu an kapalı.")
        return super().dispatch(request, *args, **kwargs)


class PasswordResetRequestView(PasswordResetFeatureMixin, PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    form_class = PasswordResetRequestForm
    email_template_name = "accounts/email/password_reset_email.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        """Same answer whether or not the address belongs to an account, so nobody can probe for accounts.

        Every request counts towards the per-IP limit (known or unknown address alike), and a per-address
        limit stops someone from flooding a victim's inbox: requests over that limit get the normal
        "sent" page but no email.
        """
        ip_key = ratelimit.request_digest(self.request)
        wait = ratelimit.check("password_reset", ip_key)
        if wait:
            form.add_error(
                None, f"Kısa sürede çok fazla istek yaptın. {ratelimit.human_wait(wait)} sonra tekrar dene."
            )
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(wait)
            return response
        ratelimit.record("password_reset", ip_key)

        email_key = ratelimit.email_digest(form.cleaned_data["email"])
        if ratelimit.check("password_reset_email", email_key) is not None:
            return HttpResponseRedirect(self.get_success_url())
        ratelimit.record("password_reset_email", email_key)
        return super().form_valid(form)


class PasswordResetSentView(PasswordResetFeatureMixin, PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetNewPasswordView(PasswordResetFeatureMixin, PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = SetNewPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")
    post_reset_login = False  # the person signs in with the new password; no automatic login


class PasswordResetFinishedView(PasswordResetFeatureMixin, PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
