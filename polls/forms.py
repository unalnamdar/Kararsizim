from django import forms
from django.db import transaction
from django.utils import timezone

from .models import (
    DURATION_CHOICES,
    DURATIONS,
    MAX_OPTIONS,
    MIN_OPTIONS,
    OPTION_MAX_LENGTH,
    QUESTION_MAX_LENGTH,
    Option,
    Poll,
    Report,
)


def _collapse_spaces(value):
    return " ".join((value or "").split())


class PollForm(forms.Form):
    """Question plus a variable list of options posted as repeated `options` fields."""

    question = forms.CharField(
        label="Sorun ne?",
        max_length=QUESTION_MAX_LENGTH,
        widget=forms.TextInput(attrs={
            "placeholder": "Bugün sinemaya mı gitsem?",
            "autocomplete": "off",
            "autofocus": True,
        }),
        error_messages={
            "required": "Bir soru yazmalısın.",
            "max_length": f"Soru en fazla {QUESTION_MAX_LENGTH} karakter olabilir.",
        },
    )

    duration = forms.ChoiceField(
        label="Anket ne kadar açık kalsın?",
        choices=DURATION_CHOICES,
        initial="none",
        required=False,  # a missing value (old forms, scripts) means "Süresiz"
        error_messages={"invalid_choice": "Geçersiz bir süre seçtin."},
        help_text="Süre dolunca oy verilemez; sonuçlar herkese açılır.",
    )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data is not None:
            self.option_values = [str(v) for v in data.getlist("options")]
        else:
            self.option_values = [""] * MIN_OPTIONS
        self.option_errors = []
        self.cleaned_options = []
        if self.is_bound:
            # After a failed submit the error summary gets the focus (site.js), not the question field.
            self.fields["question"].widget.attrs.pop("autofocus", None)

    @property
    def option_fields(self):
        """Values to re-render: at least MIN_OPTIONS inputs, never more than MAX_OPTIONS."""
        values = self.option_values[:MAX_OPTIONS]
        return values + [""] * (MIN_OPTIONS - len(values))

    def clean_question(self):
        question = _collapse_spaces(self.cleaned_data.get("question"))
        if not question:
            raise forms.ValidationError("Bir soru yazmalısın.", code="required")
        return question

    def clean_duration(self):
        return self.cleaned_data.get("duration") or "none"

    def clean(self):
        cleaned = super().clean()
        options = [_collapse_spaces(v) for v in self.option_values]
        errors = []

        if len(options) < MIN_OPTIONS:
            errors.append(f"En az {MIN_OPTIONS} seçenek eklemelisin.")
        elif len(options) > MAX_OPTIONS:
            errors.append(f"En fazla {MAX_OPTIONS} seçenek ekleyebilirsin.")

        if any(not option for option in options):
            errors.append("Seçenekler boş bırakılamaz.")
        if any(len(option) > OPTION_MAX_LENGTH for option in options):
            errors.append(f"Her seçenek en fazla {OPTION_MAX_LENGTH} karakter olabilir.")

        keys = [option.casefold() for option in options if option]
        if len(keys) != len(set(keys)):
            errors.append("Aynı seçeneği birden fazla kez yazdın.")

        if errors:
            self.option_errors = errors
            for message in errors:
                self.add_error(None, message)
        else:
            self.cleaned_options = options
        return cleaned

    @transaction.atomic
    def save(self, author):
        length = DURATIONS[self.cleaned_data["duration"]][1]
        poll = Poll.objects.create(
            author=author,
            question=self.cleaned_data["question"],
            closes_at=timezone.now() + length if length else None,
        )
        Option.objects.bulk_create(
            Option(poll=poll, text=text, position=index) for index, text in enumerate(self.cleaned_options)
        )
        return poll


class ReportForm(forms.Form):
    reason = forms.ChoiceField(
        choices=Report.Reason.choices,
        error_messages={"required": "Bir neden seç.", "invalid_choice": "Geçersiz bir neden seçtin."},
    )
    note = forms.CharField(
        max_length=200,
        required=False,
        error_messages={"max_length": "Not en fazla 200 karakter olabilir."},
    )

    def clean_note(self):
        return _collapse_spaces(self.cleaned_data.get("note"))
