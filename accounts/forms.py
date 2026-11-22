import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

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


class LoginForm(AuthenticationForm):
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

    def clean_username(self):
        return normalize_email_address(self.cleaned_data.get("username"))
