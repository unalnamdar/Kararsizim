"""Regression tests for the findings of the security review (page limit, JSON numbers, vote cap race, shared browser)."""

import json
import threading
from unittest import mock

from django.db import connection, connections
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from . import views, voting
from .models import Poll, Vote
from .tests import PASSWORD, make_poll, make_user

HUGE = "99999999999999999999"  # larger than any database integer
BROWSER_NOTE = "Bu tarayıcıdan bu ankete zaten oy verilmiş."
IP = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.7"}


class PageLimitTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        make_poll(self.owner)

    def test_absurd_page_numbers_are_404_everywhere_pages_exist(self):
        self.client.force_login(self.owner)
        for url in ["/", "/u/sahip/", "/anketlerim/"]:
            for value in (HUGE, str(views.MAX_PAGE + 1)):
                with self.subTest(url=url, page=value):
                    self.assertEqual(self.client.get(f"{url}?sayfa={value}").status_code, 404)

    def test_normal_and_odd_values_still_behave(self):
        self.assertEqual(self.client.get("/?sayfa=1").status_code, 200)
        for value in ("abc", "", "-3", "0", "1.5"):
            with self.subTest(page=value):
                self.assertEqual(self.client.get(f"/?sayfa={value}").status_code, 200)


class OptionNumberTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner, options=("Çay", "Kahve"))
        self.tea, self.coffee = self.poll.options.all()
        self.url = f"/anket/{self.poll.pk}/oy/"

    def post(self, body):
        return self.client.post(self.url, data=body, content_type="application/json", HTTP_ACCEPT="application/json")

    def test_numbers_that_are_not_whole_ids_are_a_400_not_a_500(self):
        for body in ['{"option_id": 1e400}', '{"option_id": -1e400}', '{"option_id": NaN}', '{"option_id": 1.5}']:
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": "Geçersiz seçenek."})
        self.assertFalse(Vote.objects.exists())

    def test_huge_whole_numbers_are_a_400(self):
        self.assertEqual(self.post('{"option_id": %s}' % HUGE).status_code, 400)

    def test_a_whole_number_written_with_a_decimal_point_is_accepted(self):
        self.assertEqual(self.post('{"option_id": %d.0}' % self.tea.pk).status_code, 200)
        self.assertEqual(Vote.objects.get().option, self.tea)


class VoteCapLockTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner)
        self.option = self.poll.options.first()

    def test_a_vote_locks_the_poll_row_while_it_checks_the_network_cap(self):
        """Postgres serialises concurrent votes on one poll through this row lock (SQLite ignores the hint)."""
        with mock.patch.object(
            QuerySet, "select_for_update", autospec=True, side_effect=QuerySet.select_for_update
        ) as lock:
            response = self.client.post(
                f"/anket/{self.poll.pk}/oy/",
                data=json.dumps({"option_id": self.option.pk}),
                content_type="application/json",
                **IP,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(call.args[0].model is Poll for call in lock.call_args_list))

    def test_the_cap_still_holds_one_vote_at_a_time(self):
        for n in range(voting.MAX_VOTES_PER_IP):
            client = self.client_class()
            status = client.post(
                f"/anket/{self.poll.pk}/oy/", {"option_id": self.option.pk}, **IP
            ).status_code
            self.assertEqual(status, 302, n)
        blocked = self.client_class().post(
            f"/anket/{self.poll.pk}/oy/",
            data=json.dumps({"option_id": self.option.pk}),
            content_type="application/json",
            **IP,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(Vote.objects.count(), voting.MAX_VOTES_PER_IP)


@skipUnlessDBFeature("has_select_for_update")
class VoteCapConcurrencyTests(TransactionTestCase):
    """Real parallel requests. Runs on PostgreSQL (use --keepdb against Supabase); SQLite has no row locks."""

    def test_parallel_votes_from_one_network_never_exceed_the_cap(self):
        owner = make_user("sahip")
        poll = make_poll(owner)
        option = poll.options.first()
        workers = 10  # well over the cap of 5, yet within the Session pooler's connection limit
        barrier = threading.Barrier(workers)
        statuses = []

        def cast():
            try:
                client = self.client_class()  # a fresh browser: no voter cookie
                barrier.wait(timeout=30)
                response = client.post(
                    f"/anket/{poll.pk}/oy/",
                    data=json.dumps({"option_id": option.pk}),
                    content_type="application/json",
                    **IP,
                )
                statuses.append(response.status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=cast) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        self.assertEqual(len(statuses), workers, statuses)
        self.assertEqual(Vote.objects.filter(poll=poll).count(), voting.MAX_VOTES_PER_IP, statuses)
        self.assertEqual(sorted(set(statuses)), [200, 403], statuses)


class SharedBrowserTests(TestCase):
    """A second member on the same browser must not see (or be shown as making) the first member's choice."""

    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner, question="Çay mı kahve mi?", options=("Çay", "Kahve"))
        self.tea, self.coffee = self.poll.options.all()
        self.url = f"/anket/{self.poll.pk}/oy/"
        self.ayse = make_user("ayse")
        self.deniz = make_user("deniz")

    def vote_json(self, option, client=None):
        return (client or self.client).post(
            self.url, data=json.dumps({"option_id": option.pk}), content_type="application/json"
        )

    def ayse_votes_then_deniz_signs_in(self):
        self.client.force_login(self.ayse)
        self.assertEqual(self.vote_json(self.coffee).status_code, 200)
        self.client.post("/cikis/")  # the voter_id cookie stays, like in a real shared browser
        self.client.force_login(self.deniz)

    def test_the_second_member_sees_results_but_no_choice_marked(self):
        self.ayse_votes_then_deniz_signs_in()
        page = self.client.get(self.poll.get_absolute_url()).content.decode()
        self.assertIn("options--results", page)
        self.assertNotIn("senin seçimin", page)
        self.assertNotIn("is-selected", page)
        self.assertIn(BROWSER_NOTE, page)

    def test_the_vote_attempt_is_refused_without_revealing_the_choice(self):
        self.ayse_votes_then_deniz_signs_in()
        response = self.vote_json(self.tea)
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertIsNone(body["voted_option_id"])
        self.assertEqual(body["message"], BROWSER_NOTE)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertFalse(Vote.objects.filter(user=self.deniz).exists())

    def test_no_js_form_post_gets_the_same_message(self):
        self.ayse_votes_then_deniz_signs_in()
        response = self.client.post(self.url, {"option_id": self.tea.pk}, follow=True)
        self.assertContains(response, BROWSER_NOTE)
        self.assertNotContains(response, "senin seçimin")

    def test_the_feed_card_does_not_mark_the_choice_either(self):
        self.ayse_votes_then_deniz_signs_in()
        self.assertNotContains(self.client.get("/"), "senin seçimin")

    def test_the_poll_counts_as_voted_for_the_unvoted_filter(self):
        self.ayse_votes_then_deniz_signs_in()
        self.assertNotContains(self.client.get("/?filtre=oylamadiklarim"), "Çay mı kahve mi?")

    def test_the_first_member_still_sees_their_own_choice_from_another_browser(self):
        self.client.force_login(self.ayse)
        self.vote_json(self.coffee)
        other_browser = self.client_class()
        other_browser.force_login(self.ayse)
        page = other_browser.get(self.poll.get_absolute_url()).content.decode()
        self.assertIn("senin seçimin", page)
        self.assertNotIn(BROWSER_NOTE, page)

    def test_a_guest_in_the_same_browser_still_sees_the_choice(self):
        """Logged out again, it is most likely the same person: unchanged from the original decision (karar 2)."""
        self.client.force_login(self.ayse)
        self.vote_json(self.coffee)
        self.client.post("/cikis/")
        response = self.vote_json(self.tea)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["voted_option_id"], self.coffee.pk)
        self.assertIn("senin seçimin", self.client.get(self.poll.get_absolute_url()).content.decode())

    def test_a_guest_vote_followed_by_signing_in_is_still_theirs(self):
        self.vote_json(self.tea)
        self.client.post("/giris/", {"username": self.deniz.email, "password": PASSWORD})
        response = self.vote_json(self.coffee)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["voted_option_id"], self.tea.pk)
        self.assertIn("senin seçimin", self.client.get(self.poll.get_absolute_url()).content.decode())

    def test_an_ordinary_double_vote_keeps_the_original_message(self):
        self.client.force_login(self.ayse)
        self.vote_json(self.coffee)
        body = self.vote_json(self.tea).json()
        self.assertEqual(body["message"], "Bu ankete zaten oy vermiştin.")
        self.assertEqual(body["voted_option_id"], self.coffee.pk)
