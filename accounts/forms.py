import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm

from . import ratelimit
from .models import (
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    User,
    normalize_email_address,
    normalize_username,
)

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


class SignUpForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Parola",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="En az 8 karakter; yalnızca rakamlardan oluşmamalı ve çok yaygın olmamalı.",
    )
    password2 = forms.CharField(
        label="Parola (tekrar)",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    error_messages = {
        "password_mismatch": "Parolalar birbiriyle eşleşmiyor.",
    }

    class Meta:
        model = User
        fields = ("email", "username")
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
            "username": forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none"}),
        }
        error_messages = {
            "username": {"max_length": f"Kullanıcı adı {USERNAME_MIN_LENGTH}–{USERNAME_MAX_LENGTH} karakter olmalı."},
        }
        help_texts = {
            "email": "Hiçbir yerde gösterilmez; yalnızca giriş için kullanılır.",
            "username": "Anketlerinde görünür. 3–20 karakter; harf, rakam ve alt çizgi (_).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            # After a failed submit the error summary gets the focus (site.js), not the first field.
            self.fields["email"].widget.attrs.pop("autofocus", None)

    def clean_email(self):
        email = normalize_email_address(self.cleaned_data.get("email"))
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Bu e-posta adresiyle zaten bir hesap var.", code="duplicate_email")
        return email

    def clean_username(self):
        username = normalize_username(self.cleaned_data.get("username"))
        if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
            raise forms.ValidationError(
                f"Kullanıcı adı {USERNAME_MIN_LENGTH}–{USERNAME_MAX_LENGTH} karakter olmalı.",
                code="username_length",
            )
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError(
                "Kullanıcı adı yalnızca harf (a-z), rakam ve alt çizgi (_) içerebilir.",
                code="username_chars",
            )
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Bu kullanıcı adı alınmış.", code="duplicate_username")
        return username

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(self.error_messages["password_mismatch"], code="password_mismatch")
        return password2

    def _post_clean(self):
        super()._post_clean()
        # Validate after the instance has email/username so similarity checks work.
        password = self.cleaned_data.get("password2")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginThrottleMixin:
    """Limits password guessing per network, for any address tried (site login and admin login share it).

    Only real password checks count (a malformed address never reaches one), a successful login is free, and
    while a network is locked out even the right password is refused: otherwise the limit would only slow
    the attacker down by one request per guess.
    """

    rate_limit_wait = None

    def clean(self):
        if not (self.cleaned_data.get("username") and self.cleaned_data.get("password")):
            return super().clean()
        digest = ratelimit.request_digest(self.request) if self.request is not None else None
        wait, event = ratelimit.reserve("login", digest)
        if wait:
            self.rate_limit_wait = wait
            raise forms.ValidationError(
                f"Çok fazla başarısız giriş denemesi. {ratelimit.human_wait(wait)} sonra tekrar dene.",
                code="rate_limited",
            )
        cleaned = super().clean()  # a wrong password raises here, so its attempt stays counted
        if event is not None:
            event.delete()
        return cleaned


class LoginForm(LoginThrottleMixin, AuthenticationForm):
    """Email + password. The field is named "username" by Django, but holds the email."""

    username = forms.EmailField(
        label="E-posta",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Parola",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": "E-posta veya parola hatalı.",
        "inactive": "Bu hesap etkin değil.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            # After a failed submit the error summary gets the focus (site.js), not the first field.
            self.fields["username"].widget.attrs.pop("autofocus", None)

    def clean_username(self):
        return normalize_email_address(self.cleaned_data.get("username"))


class PasswordResetRequestForm(PasswordResetForm):
    """Asks for the e-mail address. Django only mails active accounts that have a usable password."""

    email = forms.EmailField(
        label="E-posta",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
        error_messages={"required": "E-posta adresini yazmalısın.", "invalid": "Geçerli bir e-posta adresi gir."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            # After a failed submit the error summary gets the focus (site.js), not the field.
            self.fields["email"].widget.attrs.pop("autofocus", None)


class SetNewPasswordForm(SetPasswordForm):
    """New password form with the same wording and validators as sign-up."""

    error_messages = {"password_mismatch": "Parolalar birbiriyle eşleşmiyor."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Yeni parola"
        self.fields["new_password1"].help_text = (
            "En az 8 karakter; yalnızca rakamlardan oluşmamalı ve çok yaygın olmamalı."
        )
        self.fields["new_password2"].label = "Yeni parola (tekrar)"
        self.fields["new_password2"].help_text = ""  # Django's English-ish default repeats the obvious

    def clean(self):
        """A mismatch is the repeat field's error. (Skips SetPasswordForm.clean, which does the same job.)"""
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            self.add_error(
                "new_password2",
                forms.ValidationError(self.error_messages["password_mismatch"], code="password_mismatch"),
            )
        return forms.Form.clean(self)

    def _post_clean(self):
        """A weak password is the first field's error; Django would blame the repeat field."""
        forms.Form._post_clean(self)
        password = self.cleaned_data.get("new_password1")
        if password:
            try:
                password_validation.validate_password(password, self.user)
            except forms.ValidationError as error:
                self.add_error("new_password1", error)
