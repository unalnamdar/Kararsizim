from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinLengthValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 20

username_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_]+$",
    message="Kullanıcı adı yalnızca harf (a-z), rakam ve alt çizgi (_) içerebilir.",
)


def normalize_username(username):
    return (username or "").strip().lower()


def normalize_email_address(email):
    return (email or "").strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, username, password, **extra_fields):
        if not email:
            raise ValueError("E-posta adresi zorunludur.")
        if not username:
            raise ValueError("Kullanıcı adı zorunludur.")
        user = self.model(
            email=normalize_email_address(email),
            username=normalize_username(username),
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, username, password, **extra_fields)

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser için is_staff=True olmalı.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser için is_superuser=True olmalı.")
        return self._create_user(email, username, password, **extra_fields)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=normalize_email_address(email))


class User(AbstractUser):
    """Logs in with email; only the username is ever shown publicly."""

    username = models.CharField(
        "kullanıcı adı",
        max_length=USERNAME_MAX_LENGTH,
        unique=True,
        validators=[username_validator, MinLengthValidator(USERNAME_MIN_LENGTH)],
        help_text="3–20 karakter; yalnızca harf, rakam ve alt çizgi.",
        error_messages={"unique": "Bu kullanıcı adı alınmış."},
    )
    email = models.EmailField(
        "e-posta",
        unique=True,
        error_messages={"unique": "Bu e-posta adresiyle zaten bir hesap var."},
    )

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        constraints = [
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def clean(self):
        super().clean()
        self.username = normalize_username(self.username)
        self.email = normalize_email_address(self.email)

    def save(self, *args, **kwargs):
        self.username = normalize_username(self.username)
        self.email = normalize_email_address(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username
