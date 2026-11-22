from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

QUESTION_MAX_LENGTH = 200
OPTION_MAX_LENGTH = 80
MIN_OPTIONS = 2
MAX_OPTIONS = 5


class Poll(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="polls",
        verbose_name="sahibi",
    )
    question = models.CharField("soru", max_length=QUESTION_MAX_LENGTH)
    created_at = models.DateTimeField("oluşturulma", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "anket"
        verbose_name_plural = "anketler"

    def __str__(self):
        return self.question

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

    def __str__(self):
        return f"{self.poll_id} → {self.option_id}"
