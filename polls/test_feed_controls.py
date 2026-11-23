import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Vote
from .tests import make_poll, make_user
from .views import PAGE_SIZE


def key(n):
    return f"40000000-0000-4000-8000-{n:012d}"


class FeedControlsTestCase(TestCase):
    counter = 0

    def setUp(self):
        self.author = make_user("yazar")

    def add_votes(self, poll, count, days_ago=0):
        for _ in range(count):
            type(self).counter += 1
            Vote.objects.create(poll=poll, option=poll.options.first(), voter_key=key(self.counter))
        if days_ago:
            Vote.objects.filter(poll=poll).update(created_at=timezone.now() - timedelta(days=days_ago))

    def titles(self, url="/", client=None):
        response = (client or self.client).get(url)
        self.assertEqual(response.status_code, 200)
        return [poll.question for poll in response.context["polls"]]

    def vote(self, poll, client):
        return client.post(
            f"/anket/{poll.pk}/oy/",
            data=json.dumps({"option_id": poll.options.first().pk}),
            content_type="application/json",
        )


class PopularSortTests(FeedControlsTestCase):
    def test_default_is_newest_first(self):
        for name in "abc":
            make_poll(self.author, question=name)
        self.assertEqual(self.titles(), ["c", "b", "a"])

    def test_popular_ranks_by_votes_in_the_last_week_then_newest(self):
        a = make_poll(self.author, question="a")  # 1 recent vote
        b = make_poll(self.author, question="b")  # 3 recent votes
        make_poll(self.author, question="c")      # no votes
        d = make_poll(self.author, question="d")  # many votes, but all older than a week
        self.add_votes(a, 1)
        self.add_votes(b, 3)
        self.add_votes(d, 10, days_ago=8)
        self.assertEqual(self.titles("/?sirala=populer"), ["b", "a", "d", "c"])

    def test_unknown_sort_falls_back_to_newest(self):
        for name in "ab":
            make_poll(self.author, question=name)
        self.assertEqual(self.titles("/?sirala=bilinmeyen"), ["b", "a"])

    def test_popular_order_does_not_reveal_results(self):
        poll = make_poll(self.author, question="Gizli sonuç")
        self.add_votes(poll, 4)
        html = self.client.get("/?sirala=populer").content.decode()
        self.assertNotIn("option__value", html)
        self.assertNotIn("data-poll-total", html)
        self.assertIn("Oy ver, sonuçları gör", html)

    def test_pagination_keeps_the_sort_and_does_not_repeat_polls(self):
        polls = [make_poll(self.author, question=f"Soru {i:02d}") for i in range(PAGE_SIZE + 5)]
        self.add_votes(polls[3], 2)
        first = self.client.get("/?sirala=populer")
        self.assertContains(first, "sirala=populer&amp;sayfa=2")
        page1 = [p.question for p in first.context["polls"]]
        page2 = self.titles("/?sirala=populer&sayfa=2")
        self.assertEqual(page1[0], "Soru 03")
        self.assertEqual(len(page1), PAGE_SIZE)
        self.assertEqual(len(page2), 5)
        self.assertFalse(set(page1) & set(page2))

    def test_hint_is_shown_only_for_popular(self):
        self.assertNotContains(self.client.get("/"), "Son 7 günde en çok oy alanlar önde.")
        self.assertContains(self.client.get("/?sirala=populer"), "Son 7 günde en çok oy alanlar önde.")


class UnvotedFilterTests(FeedControlsTestCase):
    def setUp(self):
        super().setUp()
        self.a = make_poll(self.author, question="a")
        self.b = make_poll(self.author, question="b")
        self.c = make_poll(self.author, question="c")

    def test_member_does_not_see_polls_already_voted_on(self):
        member = make_user("uye")
        client = self.client_class()
        client.force_login(member)
        self.vote(self.a, client)
        self.assertEqual(self.titles("/?filtre=oylamadiklarim", client), ["c", "b"])
        self.assertEqual(self.titles("/", client), ["c", "b", "a"])  # unfiltered feed is unchanged

    def test_guest_is_recognised_by_the_voter_cookie(self):
        self.vote(self.b, self.client)
        self.assertEqual(self.titles("/?filtre=oylamadiklarim"), ["c", "a"])

    def test_guest_without_any_vote_sees_everything(self):
        self.assertEqual(self.titles("/?filtre=oylamadiklarim"), ["c", "b", "a"])

    def test_vote_from_the_same_browser_before_login_still_counts(self):
        self.vote(self.a, self.client)
        self.client.force_login(make_user("uye"))
        self.assertEqual(self.titles("/?filtre=oylamadiklarim"), ["c", "b"])

    def test_own_polls_the_owner_has_not_voted_on_are_included(self):
        client = self.client_class()
        client.force_login(self.author)
        self.assertEqual(self.titles("/?filtre=oylamadiklarim", client), ["c", "b", "a"])
        self.vote(self.a, client)
        self.assertEqual(self.titles("/?filtre=oylamadiklarim", client), ["c", "b"])

    def test_combines_with_popular_sort(self):
        self.add_votes(self.b, 3)
        self.add_votes(self.a, 1)
        self.vote(self.b, self.client)
        self.assertEqual(self.titles("/?sirala=populer&filtre=oylamadiklarim"), ["a", "c"])

    def test_empty_message_when_everything_is_voted(self):
        for poll in (self.a, self.b, self.c):
            self.vote(poll, self.client)
        response = self.client.get("/?filtre=oylamadiklarim")
        self.assertContains(response, "Oylamadığın anket kalmadı. Hepsine oy verdin!")
        self.assertNotContains(response, "Henüz anket yok")

    def test_pagination_keeps_the_filter(self):
        for i in range(PAGE_SIZE + 2):
            make_poll(self.author, question=f"Ek {i}")
        self.assertContains(self.client.get("/?filtre=oylamadiklarim"), "filtre=oylamadiklarim&amp;sayfa=2")


class ControlsMarkupTests(FeedControlsTestCase):
    def test_links_and_current_state(self):
        html = self.client.get("/").content.decode()
        self.assertIn('class="chip is-active" href="/" aria-current="true">Yeni', html)
        self.assertIn('href="/?sirala=populer">Popüler', html)
        self.assertIn('href="/?filtre=oylamadiklarim">Oylamadıklarım', html)

    def test_links_preserve_the_other_setting_and_toggle_the_filter_off(self):
        html = self.client.get("/?sirala=populer&filtre=oylamadiklarim").content.decode()
        self.assertIn('href="/?filtre=oylamadiklarim">Yeni', html)  # keeps the filter, drops the sort
        self.assertIn('class="chip is-active" href="/?sirala=populer&amp;filtre=oylamadiklarim" aria-current="true">Popüler', html)
        self.assertIn('class="chip is-active" href="/?sirala=populer" aria-current="true">Oylamadıklarım', html)

    def test_nav_is_labelled(self):
        self.assertContains(self.client.get("/"), '<nav class="feed-controls" aria-label="Akış seçenekleri">')

    def test_query_count_stays_constant(self):
        for i in range(12):
            poll = make_poll(make_user(f"yazar{i}"), question=f"Soru {i}")
            self.add_votes(poll, i % 3)
        with self.assertNumQueries(2):  # polls+authors, options; no identity, so no "own votes" lookup
            self.client.get("/?sirala=populer&filtre=oylamadiklarim")
        self.vote(Vote.objects.first().poll, self.client)  # now the browser has a voter cookie
        with self.assertNumQueries(3):  # + own votes (also used by the filter's subquery, which adds none)
            self.client.get("/?sirala=populer&filtre=oylamadiklarim")
