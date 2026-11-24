from django.test import TestCase

from .test_feed_controls import FeedControlsTestCase
from .tests import SECRET_EMAIL, make_poll, make_user
from .views import PAGE_SIZE


class ProfilePageTests(FeedControlsTestCase):
    def setUp(self):
        super().setUp()
        self.ayse = make_user("ayse", email=SECRET_EMAIL)
        self.first = make_poll(self.ayse, question="İlk anket")
        self.second = make_poll(self.ayse, question="İkinci anket")
        make_poll(self.author, question="Başkasının anketi")

    def test_lists_only_that_members_polls_newest_first(self):
        response = self.client.get("/u/ayse/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.question for p in response.context["polls"]], ["İkinci anket", "İlk anket"])
        self.assertNotContains(response, "Başkasının anketi")
        self.assertContains(response, "@ayse")

    def test_header_shows_poll_count_and_join_month(self):
        response = self.client.get("/u/ayse/")
        self.assertContains(response, "2 anket · Üyelik: ")
        self.assertContains(response, "<title>@ayse · Kararsızım</title>", html=False)

    def test_email_never_appears(self):
        for url in ["/u/ayse/", "/"]:
            self.assertNotContains(self.client.get(url), "gizli.adres")
        self.client.force_login(self.ayse)
        self.assertNotContains(self.client.get("/u/ayse/"), "gizli.adres")

    def test_username_in_the_address_is_case_insensitive(self):
        self.assertEqual(self.client.get("/u/AyŞe/").status_code, 404)  # not a valid username
        self.assertEqual(self.client.get("/u/AYSE/").status_code, 200)

    def test_unknown_and_inactive_members_are_404(self):
        self.assertEqual(self.client.get("/u/yok_boyle_biri/").status_code, 404)
        self.ayse.is_active = False
        self.ayse.save()
        self.assertEqual(self.client.get("/u/ayse/").status_code, 404)

    def test_voting_works_on_the_profile_and_results_stay_hidden_before(self):
        html = self.client.get("/u/ayse/").content.decode()
        self.assertIn('name="option_id"', html)
        self.assertNotIn("option__value", html)

    def test_owner_sees_a_manage_link_and_others_do_not(self):
        self.assertNotContains(self.client.get("/u/ayse/"), "Anketlerimi yönet")
        self.client.force_login(self.ayse)
        self.assertContains(self.client.get("/u/ayse/"), "Anketlerimi yönet")

    def test_no_delete_controls_on_the_profile(self):
        self.client.force_login(self.ayse)
        self.assertNotContains(self.client.get("/u/ayse/"), "/sil/")

    def test_empty_states(self):
        make_user("yeni")
        self.assertContains(self.client.get("/u/yeni/"), "@yeni henüz anket açmamış.")
        client = self.client_class()
        client.force_login(make_user("benim"))
        self.assertContains(client.get("/u/benim/"), "Henüz anket açmadın.")

    def test_pagination(self):
        for i in range(PAGE_SIZE):
            make_poll(self.ayse, question=f"Ek {i}")
        first = self.client.get("/u/ayse/")
        self.assertEqual(len(first.context["polls"]), PAGE_SIZE)
        self.assertContains(first, "sayfa=2")
        self.assertEqual(len(self.client.get("/u/ayse/?sayfa=2").context["polls"]), 2)
        self.assertEqual(self.client.get("/u/ayse/?sayfa=9").status_code, 404)

    def test_query_count_does_not_grow_with_poll_count(self):
        with self.assertNumQueries(4):  # member, polls+authors, options, poll count
            self.client.get("/u/ayse/")
        for i in range(10):
            make_poll(self.ayse, question=f"Daha {i}")
        with self.assertNumQueries(4):
            self.client.get("/u/ayse/")


class ProfileLinksTests(TestCase):
    def test_card_author_links_to_the_profile(self):
        poll = make_poll(make_user("ayse"), question="Soru")
        # Not "/anket/1/": PostgreSQL does not roll sequences back between tests, so the poll's number varies.
        for url in ["/", poll.get_absolute_url()]:
            html = self.client.get(url).content.decode()
            self.assertIn('class="poll-card__author" href="/u/ayse/">@ayse</a>', html)

    def test_menu_has_a_profile_entry_for_members_only(self):
        self.assertNotContains(self.client.get("/"), "Profilim")
        self.client.force_login(make_user("ayse"))
        self.assertContains(self.client.get("/"), 'href="/u/ayse/">Profilim')
