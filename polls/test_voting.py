import json

from django.test import TestCase

from .models import Vote
from .tests import PASSWORD, make_poll, make_user
from .voting import VOTER_COOKIE, rounded_percents


def key(n):
    return f"00000000-0000-4000-8000-{n:012d}"


class VoteTestCase(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner, question="Çay mı kahve mi?", options=("Çay", "Kahve", "İkisi de"))
        self.tea, self.coffee, self.both = self.poll.options.all()
        self.url = f"/anket/{self.poll.pk}/oy/"

    def vote_json(self, option_id, client=None):
        client = client or self.client
        return client.post(self.url, data=json.dumps({"option_id": option_id}), content_type="application/json")


class VoteEndpointTests(VoteTestCase):
    def test_anonymous_vote(self):
        response = self.vote_json(self.tea.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "total": 1,
                "options": [
                    {"id": self.tea.pk, "votes": 1, "percent": 100},
                    {"id": self.coffee.pk, "votes": 0, "percent": 0},
                    {"id": self.both.pk, "votes": 0, "percent": 0},
                ],
                "voted_option_id": self.tea.pk,
            },
        )
        vote = Vote.objects.get()
        self.assertIsNone(vote.user)
        self.assertEqual(len(vote.voter_key), 36)

        cookie = response.cookies[VOTER_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(int(cookie["max-age"]), 60 * 60 * 24 * 365)
        self.assertNotEqual(cookie.value, vote.voter_key)  # signed, not the raw key

    def test_anonymous_double_vote_409(self):
        self.vote_json(self.tea.pk)
        response = self.vote_json(self.coffee.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["voted_option_id"], self.tea.pk)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_member_vote(self):
        member = make_user("uye")
        self.client.force_login(member)
        response = self.vote_json(self.coffee.pk)
        self.assertEqual(response.status_code, 200)
        vote = Vote.objects.get()
        self.assertEqual(vote.user, member)
        self.assertEqual(vote.option, self.coffee)

    def test_member_double_vote_409_even_from_another_browser(self):
        member = make_user("uye")
        self.client.force_login(member)
        self.vote_json(self.coffee.pk)

        other_browser = self.client_class()
        other_browser.force_login(member)
        response = self.vote_json(self.tea.pk, client=other_browser)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["voted_option_id"], self.coffee.pk)
        self.assertEqual(Vote.objects.count(), 1)

    def test_guest_vote_then_login_counts_as_voted(self):
        self.vote_json(self.tea.pk)
        member = make_user("uye")
        self.client.post("/giris/", {"username": member.email, "password": PASSWORD})
        response = self.vote_json(self.coffee.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Vote.objects.count(), 1)

    def test_member_vote_then_logout_counts_as_voted(self):
        member = make_user("uye")
        self.client.force_login(member)
        self.vote_json(self.tea.pk)
        self.client.post("/cikis/")
        self.assertEqual(self.vote_json(self.coffee.pk).status_code, 409)

    def test_owner_cannot_vote(self):
        self.client.force_login(self.owner)
        response = self.vote_json(self.tea.pk)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Kendi anketine oy veremezsin."})
        self.assertFalse(Vote.objects.exists())

    def test_option_from_another_poll_rejected(self):
        other_option = make_poll(make_user("baska")).options.first()
        response = self.vote_json(other_option.pk)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Geçersiz seçenek."})
        self.assertFalse(Vote.objects.exists())

    def test_malformed_bodies_rejected(self):
        for body in ["", "not json", "[]", '{"option_id": "abc"}', '{"option_id": true}', "{}"]:
            with self.subTest(body=body):
                response = self.client.post(
                    self.url, data=body, content_type="application/json", HTTP_ACCEPT="application/json"
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(set(response.json()), {"error"})
        self.assertFalse(Vote.objects.exists())

    def test_missing_poll_404_json(self):
        response = self.client.post("/anket/999/oy/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Anket bulunamadı."})

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_csrf_enforced(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        response = self.vote_json(self.tea.pk, client=csrf_client)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Vote.objects.exists())

    def test_tampered_cookie_is_replaced(self):
        self.client.cookies[VOTER_COOKIE] = "tampered-value"
        response = self.vote_json(self.tea.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn(VOTER_COOKIE, response.cookies)

    def test_percentages_sum_to_100(self):
        Vote.objects.create(poll=self.poll, option=self.tea, voter_key=key(1))
        Vote.objects.create(poll=self.poll, option=self.coffee, voter_key=key(2))
        Vote.objects.create(poll=self.poll, option=self.both, voter_key=key(3))
        response = self.vote_json(self.tea.pk)  # 2/1/1 → 50/25/25
        self.assertEqual([o["percent"] for o in response.json()["options"]], [50, 25, 25])

        Vote.objects.create(poll=self.poll, option=self.both, voter_key=key(4))
        Vote.objects.create(poll=self.poll, option=self.coffee, voter_key=key(5))
        response = self.vote_json(self.both.pk, client=self.client_class())  # 2/2/3 → 28.6/28.6/42.9
        percents = [o["percent"] for o in response.json()["options"]]
        self.assertEqual(sum(percents), 100)
        self.assertEqual(percents, [29, 28, 43])


class RoundingTests(TestCase):
    def test_always_100(self):
        cases = [[1, 1, 1], [1, 2], [2, 2, 2, 1], [1, 1, 1, 1, 1], [7, 0, 0], [1, 1, 1, 1, 3], [123, 456, 789]]
        for counts in cases:
            with self.subTest(counts=counts):
                self.assertEqual(sum(rounded_percents(counts)), 100)

    def test_zero_total(self):
        self.assertEqual(rounded_percents([0, 0]), [0, 0])

    def test_ties_favour_earlier_option(self):
        self.assertEqual(rounded_percents([1, 1, 1]), [34, 33, 33])


class NoJsFallbackTests(VoteTestCase):
    def test_form_post_redirects_to_detail_with_message(self):
        response = self.client.post(self.url, {"option_id": self.tea.pk}, follow=True)
        self.assertRedirects(response, f"/anket/{self.poll.pk}/")
        self.assertContains(response, "Oyun kaydedildi.")
        self.assertContains(response, "<strong>%100</strong>", html=False)
        self.assertEqual(Vote.objects.count(), 1)

    def test_form_post_double_vote(self):
        self.client.post(self.url, {"option_id": self.tea.pk})
        response = self.client.post(self.url, {"option_id": self.coffee.pk}, follow=True)
        self.assertContains(response, "Bu ankete zaten oy vermiştin.")
        self.assertEqual(Vote.objects.count(), 1)

    def test_form_post_invalid_option(self):
        response = self.client.post(self.url, {"option_id": "x"}, follow=True)
        self.assertContains(response, "Geçersiz seçenek.")
        self.assertFalse(Vote.objects.exists())

    def test_form_post_owner(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"option_id": self.tea.pk}, follow=True)
        self.assertContains(response, "Kendi anketine oy veremezsin.")
        self.assertFalse(Vote.objects.exists())


class ResultVisibilityTests(VoteTestCase):
    def setUp(self):
        super().setUp()
        # Votes from other people, so there are numbers that could leak.
        for i in range(3):
            Vote.objects.create(poll=self.poll, option=self.coffee, voter_key=key(i))

    def assert_no_results(self, response):
        self.assertNotContains(response, "option__value")
        self.assertNotContains(response, "data-poll-total")
        self.assertNotContains(response, "· 3 oy")
        self.assertContains(response, "Oy ver, sonuçları gör")
        self.assertContains(response, f'action="/anket/{self.poll.pk}/oy/"')

    def test_results_hidden_before_voting(self):
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            with self.subTest(url=url, as_="guest"):
                self.assert_no_results(self.client.get(url))
        self.client.force_login(make_user("uye"))
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            with self.subTest(url=url, as_="member"):
                self.assert_no_results(self.client.get(url))

    def test_error_responses_contain_no_results(self):
        for response in [
            self.vote_json(999999),
            self.client.post(self.url, data="{}", content_type="application/json"),
        ]:
            self.assertEqual(set(response.json()), {"error"})

    def test_results_visible_after_voting_and_persist(self):
        self.vote_json(self.tea.pk)
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "<strong>%75</strong> · 3 oy", html=False)
                self.assertContains(response, "<strong>%25</strong> · 1 oy", html=False)
                self.assertContains(response, "is-selected", count=1)
                self.assertContains(response, "<span data-poll-total>4</span> oy", html=False)
                self.assertNotContains(response, 'name="option_id"')

    def test_owner_always_sees_results_and_no_vote_buttons(self):
        self.client.force_login(self.owner)
        for url in ["/", f"/anket/{self.poll.pk}/", "/anketlerim/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "<strong>%100</strong> · 3 oy", html=False)
                self.assertContains(response, "Senin anketin")
                self.assertNotContains(response, 'name="option_id"')
                self.assertNotContains(response, "is-selected")

    def test_owner_sees_zero_votes(self):
        poll = make_poll(self.owner, question="Boş anket")
        self.client.force_login(self.owner)
        response = self.client.get(f"/anket/{poll.pk}/")
        self.assertContains(response, "<span data-poll-total>0</span> oy", html=False)
        self.assertContains(response, "<strong>%0</strong> · 0 oy", html=False)

    def test_feed_query_count_with_votes(self):
        for i in range(5):
            poll = make_poll(make_user(f"yazar{i}"))
            Vote.objects.create(poll=poll, option=poll.options.first(), voter_key=key(100 + i))
        self.vote_json(self.tea.pk)  # sets the voter cookie
        with self.assertNumQueries(3):  # polls+authors, options+counts, own votes
            self.client.get("/")
