from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

QUESTION_MAX_LENGTH = 200
OPTION_MAX_LENGTH = 80
MIN_OPTIONS = 2
MAX_OPTIONS = 5

# How long a poll stays open, chosen by its author when creating it (value -> (label, length; None = no end)).
DURATIONS = {
    "none": ("Süresiz", None),
    "1h": ("1 saat", timedelta(hours=1)),
    "1d": ("1 gün", timedelta(days=1)),
    "3d": ("3 gün", timedelta(days=3)),
    "7d": ("7 gün", timedelta(days=7)),
}
DURATION_CHOICES = [(value, label) for value, (label, _) in DURATIONS.items()]


class Poll(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="polls",
        verbose_name="sahibi",
    )
    question = models.CharField("soru", max_length=QUESTION_MAX_LENGTH)
    created_at = models.DateTimeField("oluşturulma", auto_now_add=True, db_index=True)
    # NULL = no end (every poll made before this field existed, and "Süresiz"). Never changes after creation.
    closes_at = models.DateTimeField("bitiş", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "anket"
        verbose_name_plural = "anketler"

    def __str__(self):
        return self.question

    @property
    def is_open(self):
        return self.closes_at is None or timezone.now() < self.closes_at

    def get_absolute_url(self):
        return reverse("polls:detail", args=[self.pk])


class Option(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options", verbose_name="anket")
    text = models.CharField("seçenek", max_length=OPTION_MAX_LENGTH)
    position = models.PositiveSmallIntegerField(
        "sıra",
        validators=[MinValueValidator(0), MaxValueValidator(MAX_OPTIONS - 1)],
    )

    class Meta:
        ordering = ["position"]
        verbose_name = "seçenek"
        verbose_name_plural = "seçenekler"
        constraints = [
            models.UniqueConstraint(fields=["poll", "position"], name="polls_option_unique_position"),
            models.CheckConstraint(
                condition=models.Q(position__lte=MAX_OPTIONS - 1),
                name="polls_option_position_range",
            ),
        ]

    def __str__(self):
        return self.text


class Vote(models.Model):
    """One vote per person per poll.

    `user` is set for members. `voter_key` holds the signed `voter_id` cookie value and is
    stored for every vote (members included), so the same browser is recognised even after
    logging in or out.
    """

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes", verbose_name="anket")
    option = models.ForeignKey(Option, on_delete=models.CASCADE, related_name="votes", verbose_name="seçenek")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="votes",
        verbose_name="üye",
    )
    voter_key = models.CharField("ziyaretçi kimliği", max_length=36, null=True, blank=True)
    # Keyed hash of the voter's IP (never the IP itself); NULL when the IP was unknown.
    ip_hash = models.CharField("IP özeti", max_length=32, null=True, blank=True)
    created_at = models.DateTimeField("oy zamanı", auto_now_add=True)

    class Meta:
        verbose_name = "oy"
        verbose_name_plural = "oylar"
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "user"],
                condition=models.Q(user__isnull=False),
                name="polls_vote_unique_user",
            ),
            models.UniqueConstraint(
                fields=["poll", "voter_key"],
                condition=models.Q(voter_key__isnull=False),
                name="polls_vote_unique_voter_key",
            ),
            models.CheckConstraint(
                condition=models.Q(user__isnull=False) | models.Q(voter_key__isnull=False),
                name="polls_vote_has_identity",
            ),
        ]
        indexes = [models.Index(fields=["poll", "ip_hash"], name="polls_vote_poll_ip")]

    def __str__(self):
        return f"{self.poll_id} → {self.option_id}"


class Report(models.Model):
    """A visitor's report about a poll. Only visible in the admin; nothing is hidden automatically."""

    class Reason(models.TextChoices):
        SPAM = "spam", "Spam ya da reklam"
        ABUSIVE = "abusive", "Hakaret ya da uygunsuz içerik"
        OTHER = "other", "Diğer"

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="reports", verbose_name="anket")
    # "u<user id>" for members, "i<ip digest>" for guests: at most one report per person per poll.
    reporter = models.CharField("bildiren", max_length=40)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="üye",
    )
    reason = models.CharField("neden", max_length=16, choices=Reason.choices)
    note = models.CharField("not", max_length=200, blank=True)
    created_at = models.DateTimeField("bildirim zamanı", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "bildirim"
        verbose_name_plural = "bildirimler"
        constraints = [
            models.UniqueConstraint(fields=["poll", "reporter"], name="polls_report_unique_reporter"),
        ]

    def __str__(self):
        return f"{self.poll_id}: {self.get_reason_display()}"
