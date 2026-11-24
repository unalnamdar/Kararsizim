"""Poll end time (Faz 6, decision 12) and changing a vote within 10 minutes of casting it."""

import json
from datetime import timedelta

from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from accounts.models import RateLimitEvent

from . import voting
from .forms import PollForm
from .models import DURATION_CHOICES, DURATIONS, Poll, Vote
from .tests import PASSWORD, make_poll, make_user

IP = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.7"}
CLOSED_MESSAGE = "Bu anketin süresi doldu."
LOCKED_MESSAGE = "Oyunu değiştirme süren doldu."
CHANGED_MESSAGE = "Oyun değişti."
TIME_LEFT = r"\d\s(dakika|saat|gün)[^<]* kaldı"  # "kaldın" also appears in the site description


class PollCase(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner, question="Çay mı kahve mi?", options=("Çay", "Kahve", "İkisi de"))
        self.tea, self.coffee, self.both = self.poll.options.all()
        self.url = f"/anket/{self.poll.pk}/oy/"

    def vote(self, option, client=None, url=None, **meta):
        return (client or self.client).post(
            url or self.url, data=json.dumps({"option_id": option.pk}), content_type="application/json", **meta
        )

    def close(self, poll=None, ago=timedelta(minutes=1)):
        poll = poll or self.poll
        Poll.objects.filter(pk=poll.pk).update(closes_at=timezone.now() - ago)

    def age_votes(self, minutes):
        Vote.objects.update(created_at=timezone.now() - timedelta(minutes=minutes))

    def counts(self):
        return {o.text: o.votes.count() for o in self.poll.options.all()}


class DurationChoiceTests(TestCase):
    def test_the_choices(self):
        self.assertEqual(
            DURATION_CHOICES,
            [("none", "Süresiz"), ("1h", "1 saat"), ("1d", "1 gün"), ("3d", "3 gün"), ("7d", "7 gün")],
        )

    def test_the_create_form_offers_them_with_suresiz_selected(self):
        user = make_user("sahip")
        self.client.force_login(user)
        page = self.client.get("/anket/yeni/").content.decode()
        self.assertIn('<select name="duration"', page)
        for value, label in DURATION_CHOICES:
            self.assertIn(f'<option value="{value}"', page)
            self.assertIn(label, page)
        self.assertIn('<option value="none" selected>', page)

    def create(self, **extra):
        data = {"question": "Bugün ne yapsam?", "options": ["Sinema", "Restoran"], **extra}
        return self.client.post("/anket/yeni/", data)

    def test_each_choice_sets_the_end_time(self):
        self.client.force_login(make_user("sahip"))
        for value, (_, length) in DURATIONS.items():
            with self.subTest(duration=value):
                before = timezone.now()
                self.assertEqual(self.create(duration=value).status_code, 302)
                poll = Poll.objects.latest("pk")
                if length is None:
                    self.assertIsNone(poll.closes_at)
                else:
                    self.assertTrue(before + length <= poll.closes_at <= timezone.now() + length)

    def test_a_missing_choice_means_suresiz(self):
        self.client.force_login(make_user("sahip"))
        self.create()
        self.assertIsNone(Poll.objects.get().closes_at)

    def test_an_unknown_choice_is_rejected_with_the_error_summary(self):
        self.client.force_login(make_user("sahip"))
        response = self.create(duration="forever")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-error-summary")
        self.assertContains(response, "Geçersiz bir süre seçtin.")
        self.assertFalse(Poll.objects.exists())

    def test_the_form_keeps_the_chosen_duration_after_an_error(self):
        form = PollForm(QueryDict("question=&options=a&options=b&duration=3d"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form["duration"].value(), "3d")


class PollIsOpenTests(TestCase):
    def test_is_open(self):
        poll = make_poll(make_user("sahip"))
        self.assertTrue(poll.is_open)  # no end
        poll.closes_at = timezone.now() + timedelta(minutes=5)
        self.assertTrue(poll.is_open)
        poll.closes_at = timezone.now() - timedelta(seconds=1)
        self.assertFalse(poll.is_open)


class ClosedPollTests(PollCase):
    def test_nobody_can_vote_and_the_answer_carries_the_results(self):
        self.vote(self.tea, client=self.client_class())  # someone voted while it was open
        self.close()
        response = self.vote(self.coffee)
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["message"], CLOSED_MESSAGE)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["can_change"])
        self.assertIsNone(body["voted_option_id"])
        self.assertEqual(Vote.objects.count(), 1)

    def test_a_vote_made_before_the_end_cannot_be_changed_any_more(self):
        self.vote(self.tea)
        self.close()
        response = self.vote(self.coffee)  # still inside the 10 minutes, but the poll has ended
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], CLOSED_MESSAGE)
        self.assertEqual(response.json()["voted_option_id"], self.tea.pk)  # their own choice is still shown to them
        self.assertEqual(Vote.objects.get().option, self.tea)

    def test_the_owner_cannot_vote_either(self):
        self.client.force_login(self.owner)
        self.close()
        self.assertEqual(self.vote(self.tea).status_code, 409)
        self.assertFalse(Vote.objects.exists())

    def test_no_js_form_post_gets_the_message_on_the_poll_page(self):
        self.close()
        response = self.client.post(self.url, {"option_id": self.tea.pk}, follow=True)
        self.assertRedirects(response, f"/anket/{self.poll.pk}/")
        self.assertContains(response, CLOSED_MESSAGE)
        self.assertFalse(Vote.objects.exists())

    def test_everybody_sees_the_results_without_voting(self):
        self.vote(self.tea, client=self.client_class())
        self.vote(self.tea, client=self.client_class())
        self.vote(self.coffee, client=self.client_class())
        self.close()
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()  # a guest who never voted
                self.assertIn("<strong>%67</strong> · 2 oy", page)
                self.assertIn("<strong>%33</strong> · 1 oy", page)
                self.assertIn("Sona erdi", page)
                self.assertNotIn('name="option_id"', page)  # no bars to press
                self.assertNotIn("is-selected", page)
                self.assertNotRegex(page, TIME_LEFT)

    def test_a_voter_still_sees_their_own_choice(self):
        self.vote(self.coffee)
        self.close()
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertEqual(page.count("is-selected"), 1)
        self.assertIn("senin seçimin", page)
        self.assertNotIn('name="option_id"', page)

    def test_ended_polls_stay_in_the_feed_and_the_popular_list(self):
        self.close()
        for url in ["/", "/?sirala=populer"]:
            self.assertContains(self.client.get(url), "Çay mı kahve mi?")

    def test_ended_polls_do_not_count_as_not_voted_yet(self):
        open_poll = make_poll(self.owner, question="Hâlâ açık mı?")
        self.close()
        page = self.client.get("/?filtre=oylamadiklarim").content.decode()
        self.assertIn("Hâlâ açık mı?", page)
        self.assertNotIn("Çay mı kahve mi?", page)
        self.assertTrue(open_poll.is_open)


class OpenPollWithEndTests(PollCase):
    def test_the_card_shows_the_time_left(self):
        Poll.objects.filter(pk=self.poll.pk).update(closes_at=timezone.now() + timedelta(days=2, hours=3))
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertRegex(page, r"2 gün, [23] saat kaldı")  # timeuntil joins the numbers with a no-break space
        self.assertNotIn("Sona erdi", page)

    def test_a_poll_without_an_end_shows_nothing_about_time(self):
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertNotRegex(page, TIME_LEFT)
        self.assertNotIn("Sona erdi", page)

    def test_voting_works_normally_before_the_end(self):
        Poll.objects.filter(pk=self.poll.pk).update(closes_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.vote(self.tea).status_code, 200)

    def test_open_polls_stay_in_the_not_voted_filter(self):
        Poll.objects.filter(pk=self.poll.pk).update(closes_at=timezone.now() + timedelta(hours=1))
        self.assertContains(self.client.get("/?filtre=oylamadiklarim"), "Çay mı kahve mi?")


class ChangeSecondsTests(PollCase):
    def test_the_window_runs_from_the_first_vote(self):
        now = timezone.now()
        self.assertEqual(voting.change_seconds_left(self.poll, now - timedelta(minutes=4), now), 360)
        self.assertEqual(voting.change_seconds_left(self.poll, now - timedelta(minutes=10), now), 0)
        self.assertEqual(voting.change_seconds_left(self.poll, now - timedelta(minutes=11), now), 0)
        self.assertEqual(voting.change_seconds_left(self.poll, None, now), 0)

    def test_a_poll_that_ends_sooner_shortens_the_window(self):
        now = timezone.now()
        self.poll.closes_at = now + timedelta(minutes=3)
        self.assertEqual(voting.change_seconds_left(self.poll, now, now), 180)
        self.poll.closes_at = now - timedelta(seconds=1)
        self.assertEqual(voting.change_seconds_left(self.poll, now, now), 0)


class ChangeVoteTests(PollCase):
    def test_a_vote_can_be_moved_to_another_option(self):
        self.vote(self.tea)
        created = Vote.objects.get().created_at
        response = self.vote(self.coffee)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["voted_option_id"], self.coffee.pk)
        self.assertTrue(body["can_change"])
        self.assertEqual(body["total"], 1)
        self.assertEqual([o["votes"] for o in body["options"]], [0, 1, 0])
        self.assertEqual(Vote.objects.count(), 1)  # moved, not added
        vote = Vote.objects.get()
        self.assertEqual(vote.option, self.coffee)
        self.assertEqual(vote.created_at, created)  # the window does not restart

    def test_the_same_option_again_changes_nothing(self):
        self.vote(self.tea)
        response = self.vote(self.tea)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("changed", response.json())
        self.assertEqual(Vote.objects.get().option, self.tea)

    def test_it_can_be_changed_several_times_inside_the_window(self):
        self.vote(self.tea)
        for option in (self.coffee, self.both, self.tea):
            self.assertEqual(self.vote(option).status_code, 200)
        self.assertEqual(Vote.objects.get().option, self.tea)

    def test_other_peoples_votes_are_untouched(self):
        self.vote(self.tea, client=self.client_class())
        self.vote(self.coffee, client=self.client_class())
        mine = self.client_class()
        self.vote(self.tea, client=mine)
        self.vote(self.both, client=mine)
        self.assertEqual(self.counts(), {"Çay": 1, "Kahve": 1, "İkisi de": 1})

    def test_just_inside_and_just_outside_the_window(self):
        self.vote(self.tea)
        self.age_votes(9.97)  # 9 minutes 58 seconds
        self.assertEqual(self.vote(self.coffee).status_code, 200)
        self.age_votes(10.03)  # 10 minutes 2 seconds
        response = self.vote(self.both)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], LOCKED_MESSAGE)
        self.assertEqual(response.json()["voted_option_id"], self.coffee.pk)
        self.assertEqual(Vote.objects.get().option, self.coffee)

    def test_changing_does_not_extend_the_window(self):
        self.vote(self.tea)
        self.age_votes(9)
        first_cast = Vote.objects.get().created_at
        self.assertEqual(self.vote(self.coffee).status_code, 200)  # change at minute 9
        self.assertEqual(Vote.objects.get().created_at, first_cast)  # still counted from the first vote
        self.assertTrue(timezone.now() - first_cast >= timedelta(minutes=9))
        self.age_votes(10.5)
        self.assertEqual(self.vote(self.both).status_code, 409)

    def test_a_locked_vote_is_not_counted_as_a_change_in_the_payload(self):
        self.vote(self.tea)
        self.age_votes(11)
        body = self.vote(self.coffee).json()
        self.assertFalse(body["can_change"])
        self.assertEqual(body["change_seconds"], 0)
        self.assertNotIn("changed", body)

    def test_the_same_member_can_change_from_another_browser(self):
        member = make_user("uye")
        self.client.force_login(member)
        self.vote(self.tea)
        other = self.client_class()
        other.force_login(member)
        self.assertEqual(self.vote(self.coffee, client=other).status_code, 200)
        self.assertEqual(Vote.objects.get().option, self.coffee)

    def test_a_guest_can_change_after_signing_in(self):
        self.vote(self.tea)
        member = make_user("uye")
        self.client.post("/giris/", {"username": member.email, "password": PASSWORD})
        self.assertEqual(self.vote(self.coffee).status_code, 200)
        self.assertEqual(Vote.objects.get().option, self.coffee)

    def test_a_different_member_on_the_same_browser_cannot_change_it(self):
        ayse, deniz = make_user("ayse"), make_user("deniz")
        self.client.force_login(ayse)
        self.vote(self.tea)
        self.client.post("/cikis/")
        self.client.force_login(deniz)
        response = self.vote(self.coffee)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "Bu tarayıcıdan bu ankete zaten oy verilmiş.")
        self.assertIsNone(response.json()["voted_option_id"])
        self.assertEqual(Vote.objects.get().option, self.tea)

    def test_a_poll_ending_during_the_window_stops_changes(self):
        self.vote(self.tea)
        self.close(ago=timedelta(seconds=1))
        self.assertEqual(self.vote(self.coffee).status_code, 409)
        self.assertEqual(Vote.objects.get().option, self.tea)

    def test_changing_does_not_use_up_the_network_cap(self):
        browsers = [self.client_class() for _ in range(voting.MAX_VOTES_PER_IP)]
        for browser in browsers:
            self.assertEqual(self.vote(self.tea, client=browser, **IP).status_code, 200)
        self.assertEqual(self.vote(self.coffee, client=browsers[0], **IP).status_code, 200)  # not a 403
        self.assertEqual(Vote.objects.count(), voting.MAX_VOTES_PER_IP)
        self.assertEqual(self.vote(self.tea, client=self.client_class(), **IP).status_code, 403)  # still capped

    def test_a_change_counts_for_the_vote_rate_limit(self):
        self.vote(self.tea, **IP)
        before = RateLimitEvent.objects.filter(scope="vote").count()
        self.vote(self.coffee, **IP)
        self.assertEqual(RateLimitEvent.objects.filter(scope="vote").count(), before + 1)

    def test_no_js_form_post_changes_the_vote_with_a_message(self):
        self.client.post(self.url, {"option_id": self.tea.pk})
        response = self.client.post(self.url, {"option_id": self.coffee.pk}, follow=True)
        self.assertContains(response, CHANGED_MESSAGE)
        self.assertEqual(Vote.objects.get().option, self.coffee)

    def test_an_invalid_option_does_not_touch_the_vote(self):
        self.vote(self.tea)
        other_poll_option = make_poll(self.owner).options.first()
        self.assertEqual(self.vote(other_poll_option).status_code, 400)
        self.assertEqual(Vote.objects.get().option, self.tea)


class ChangeVotePageTests(PollCase):
    def test_right_after_voting_the_bars_are_buttons_with_the_choice_marked(self):
        self.vote(self.coffee)
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()
                self.assertEqual(page.count('name="option_id"'), 3)  # every bar can be pressed
                self.assertEqual(page.count("is-selected"), 1)
                self.assertIn("(senin seçimin)", page)
                self.assertIn("✓", page)
                self.assertIn("Oyunu 10 dakika daha değiştirebilirsin.", page)
                self.assertIn("oyunu değiştirmek için başka bir seçeneğe dokunabilirsin", page)

    def test_the_minutes_shrink_as_time_passes(self):
        self.vote(self.tea)
        self.age_votes(6.5)
        self.assertContains(self.client.get(f"/anket/{self.poll.pk}/"), "Oyunu 4 dakika daha değiştirebilirsin.")

    def test_after_the_window_the_bars_are_plain_text_again(self):
        self.vote(self.tea)
        self.age_votes(10.5)
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertNotIn('name="option_id"', page)
        self.assertNotIn("dakika daha değiştirebilirsin", page)
        self.assertEqual(page.count("is-selected"), 1)

    def test_the_form_posts_to_the_vote_url_with_a_csrf_token(self):
        self.vote(self.tea)
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertIn(f'action="/anket/{self.poll.pk}/oy/"', page)
        self.assertIn("csrfmiddlewaretoken", page)

    def test_someone_who_has_not_voted_sees_no_results(self):
        self.vote(self.tea)
        page = self.client_class().get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertNotIn("%100", page)
        self.assertNotIn("dakika daha değiştirebilirsin", page)

    def test_a_different_member_on_the_same_browser_gets_no_buttons(self):
        ayse, deniz = make_user("ayse"), make_user("deniz")
        self.client.force_login(ayse)
        self.vote(self.tea)
        self.client.post("/cikis/")
        self.client.force_login(deniz)
        page = self.client.get(f"/anket/{self.poll.pk}/").content.decode()
        self.assertNotIn('name="option_id"', page)
        self.assertNotIn("dakika daha değiştirebilirsin", page)
        self.assertNotIn("is-selected", page)

    def test_the_owner_can_change_their_own_vote_too(self):
        self.client.force_login(self.owner)
        self.vote(self.tea)
        self.assertEqual(self.vote(self.coffee).status_code, 200)
        self.assertEqual(Vote.objects.get().option, self.coffee)
        self.assertContains(self.client.get(f"/anket/{self.poll.pk}/"), "Oyunu 10 dakika daha değiştirebilirsin.")

    def test_the_markup_has_no_dangling_aria_references(self):
        from config.test_design import dangling_references

        self.vote(self.tea)
        self.assertEqual(dangling_references(self.client.get(f"/anket/{self.poll.pk}/").content.decode()), [])
