from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Option, Poll
from .views import PAGE_SIZE

User = get_user_model()
PASSWORD = "g8#kLq!29zPa"
SECRET_EMAIL = "gizli.adres.123@example.com"


def make_user(username="ayse", email=None):
    return User.objects.create_user(email=email or f"{username}@example.com", username=username, password=PASSWORD)


def make_poll(author, question="Sinema mı, restoran mı?", options=("Sinema", "Restoran")):
    poll = Poll.objects.create(author=author, question=question)
    Option.objects.bulk_create(Option(poll=poll, text=text, position=i) for i, text in enumerate(options))
    return poll


class CreatePollTests(TestCase):
    url = "/anket/yeni/"

    def setUp(self):
        self.user = make_user()

    def post(self, question="Bugün ne yapsam?", options=("Sinema", "Restoran")):
        return self.client.post(self.url, {"question": question, "options": list(options)})

    def test_guest_is_redirected_to_login_with_next(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, "/giris/?next=/anket/yeni/")

    def test_guest_returns_to_form_after_login(self):
        response = self.client.post(
            "/giris/?next=/anket/yeni/",
            {"username": self.user.email, "password": PASSWORD, "next": "/anket/yeni/"},
        )
        self.assertRedirects(response, self.url)

    def test_form_opens_with_two_option_fields(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="options"', count=3)  # 2 fields + 1 in <template>

    def test_valid_poll_is_created(self):
        self.client.force_login(self.user)
        response = self.post(question="  Bugün   ne yapsam? ", options=["Sinema", " Restoran ", "Evde kal"])
        poll = Poll.objects.get()
        self.assertRedirects(response, f"/anket/{poll.pk}/")
        self.assertEqual(poll.author, self.user)
        self.assertEqual(poll.question, "Bugün ne yapsam?")
        self.assertEqual(
            list(poll.options.values_list("text", "position")),
            [("Sinema", 0), ("Restoran", 1), ("Evde kal", 2)],
        )

    def test_five_options_allowed(self):
        self.client.force_login(self.user)
        self.post(options=["A", "B", "C", "D", "E"])
        self.assertEqual(Option.objects.count(), 5)

    def assert_rejected(self, response, message):
        self.assertEqual(response.status_code, 200)
        self.assertIn(message, response.context["form"].option_errors)
        self.assertFalse(Poll.objects.exists())
        self.assertFalse(Option.objects.exists())

    def test_one_option_rejected(self):
        self.client.force_login(self.user)
        self.assert_rejected(self.post(options=["Sinema"]), "En az 2 seçenek eklemelisin.")

    def test_no_options_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"question": "Soru?"})
        self.assert_rejected(response, "En az 2 seçenek eklemelisin.")

    def test_six_options_rejected(self):
        self.client.force_login(self.user)
        self.assert_rejected(self.post(options=["A", "B", "C", "D", "E", "F"]), "En fazla 5 seçenek ekleyebilirsin.")

    def test_empty_option_rejected(self):
        self.client.force_login(self.user)
        self.assert_rejected(self.post(options=["Sinema", "   ", "Restoran"]), "Seçenekler boş bırakılamaz.")

    def test_duplicate_options_rejected_case_insensitively(self):
        self.client.force_login(self.user)
        self.assert_rejected(self.post(options=["Sinema", "sinema "]), "Aynı seçeneği birden fazla kez yazdın.")

    def test_too_long_option_rejected(self):
        self.client.force_login(self.user)
        self.assert_rejected(self.post(options=["A" * 81, "B"]), "Her seçenek en fazla 80 karakter olabilir.")

    def test_question_required_and_limited(self):
        self.client.force_login(self.user)
        for question, message in [("   ", "Bir soru yazmalısın."), ("x" * 201, "Soru en fazla 200 karakter olabilir.")]:
            with self.subTest(question=question[:10]):
                response = self.post(question=question)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.context["form"].errors["question"])
        self.assertFalse(Poll.objects.exists())

    def test_rejected_form_keeps_entered_options(self):
        self.client.force_login(self.user)
        response = self.post(options=["Sinema", "Sinema", "Tiyatro"])
        self.assertContains(response, 'value="Tiyatro"')


class FeedTests(TestCase):
    def setUp(self):
        self.author = make_user()

    def test_empty_state(self):
        response = self.client.get("/")
        self.assertContains(response, "Henüz anket yok. İlk kararsız sen ol!")
        self.assertContains(response, 'href="/anket/yeni/"')

    def test_newest_first(self):
        first = make_poll(self.author, question="Birinci soru")
        second = make_poll(self.author, question="İkinci soru")
        polls = list(self.client.get("/").context["polls"])
        self.assertEqual(polls, [second, first])

    def test_shows_author_question_options(self):
        make_poll(self.author, question="Çay mı kahve mi?", options=("Çay", "Kahve"))
        response = self.client.get("/")
        self.assertContains(response, "@ayse")
        self.assertContains(response, "Çay mı kahve mi?")
        self.assertContains(response, "Kahve")

    def test_pagination(self):
        for i in range(PAGE_SIZE + 3):
            make_poll(self.author, question=f"Soru {i}")

        page1 = self.client.get("/")
        self.assertEqual(len(page1.context["polls"]), PAGE_SIZE)
        self.assertEqual(page1.context["polls"][0].question, f"Soru {PAGE_SIZE + 2}")
        self.assertContains(page1, 'href="?sayfa=2"')

        page2 = self.client.get("/?sayfa=2")
        self.assertEqual([p.question for p in page2.context["polls"]], ["Soru 2", "Soru 1", "Soru 0"])
        self.assertNotContains(page2, "Daha fazla")

        self.assertEqual(self.client.get("/?sayfa=3").status_code, 404)
        self.assertEqual(self.client.get("/?sayfa=abc").status_code, 200)

    def test_query_count_does_not_grow_with_poll_count(self):
        for i in range(3):
            make_poll(make_user(f"user{i}"), options=("A", "B", "C"))
        with self.assertNumQueries(2):  # polls+authors, options
            self.client.get("/")

        for i in range(3, 15):
            make_poll(make_user(f"user{i}"), options=("A", "B", "C", "D"))
        with self.assertNumQueries(2):
            self.client.get("/")

    def test_query_count_for_member(self):
        for i in range(5):
            make_poll(make_user(f"user{i}"))
        self.client.force_login(self.author)
        with self.assertNumQueries(5):  # session, user, polls+authors, options+counts, own votes
            self.client.get("/")


class DetailTests(TestCase):
    def test_detail_page(self):
        poll = make_poll(make_user(), question="Deniz mi dağ mı?", options=("Deniz", "Dağ"))
        response = self.client.get(f"/anket/{poll.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Deniz mi dağ mı? · Kararsızım</title>", html=False)
        self.assertContains(response, "Dağ")

    def test_missing_poll_404(self):
        self.assertEqual(self.client.get("/anket/999/").status_code, 404)

    def test_delete_control_only_for_owner(self):
        owner = make_user("sahip")
        poll = make_poll(owner)
        delete_action = f'action="/anket/{poll.pk}/sil/"'

        self.assertNotContains(self.client.get(poll.get_absolute_url()), delete_action)
        self.client.force_login(make_user("baska"))
        self.assertNotContains(self.client.get(poll.get_absolute_url()), delete_action)
        self.client.force_login(owner)
        self.assertContains(self.client.get(poll.get_absolute_url()), delete_action)


class MyPollsTests(TestCase):
    def test_requires_login(self):
        self.assertRedirects(self.client.get("/anketlerim/"), "/giris/?next=/anketlerim/")

    def test_lists_only_own_polls(self):
        me, other = make_user("ben"), make_user("o")
        mine = make_poll(me, question="Benim sorum")
        make_poll(other, question="Onun sorusu")
        self.client.force_login(me)
        response = self.client.get("/anketlerim/")
        self.assertEqual(list(response.context["polls"]), [mine])
        self.assertNotContains(response, "Onun sorusu")

    def test_empty_state(self):
        self.client.force_login(make_user())
        self.assertContains(self.client.get("/anketlerim/"), "Henüz anket açmadın.")


class DeletePollTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner)
        self.url = f"/anket/{self.poll.pk}/sil/"

    def test_owner_can_delete(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url)
        self.assertRedirects(response, "/anketlerim/")
        self.assertFalse(Poll.objects.exists())
        self.assertFalse(Option.objects.exists())

    def test_other_member_gets_403(self):
        self.client.force_login(make_user("baska"))
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Poll.objects.exists())

    def test_guest_gets_403(self):
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Poll.objects.exists())

    def test_get_not_allowed(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(Poll.objects.exists())

    def test_missing_poll_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post("/anket/999/sil/").status_code, 404)


class EmailPrivacyTests(TestCase):
    def test_email_never_rendered(self):
        author = make_user("gizli", email=SECRET_EMAIL)
        poll = make_poll(author)
        pages_as_guest = ["/", poll.get_absolute_url(), "/giris/", "/kayit/"]
        pages_as_author = pages_as_guest[:2] + ["/anketlerim/", "/anket/yeni/"]

        for url in pages_as_guest:
            with self.subTest(url=url, as_="guest"):
                self.assertNotContains(self.client.get(url), SECRET_EMAIL)

        self.client.force_login(author)
        for url in pages_as_author:
            with self.subTest(url=url, as_="author"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, SECRET_EMAIL)
                self.assertNotContains(response, "gizli.adres")


class HeaderLinksTests(TestCase):
    def test_create_button_for_everyone_and_my_polls_for_members(self):
        guest = self.client.get("/")
        self.assertContains(guest, 'href="/anket/yeni/"')
        self.assertNotContains(guest, 'href="/anketlerim/"')

        self.client.force_login(make_user())
        member = self.client.get("/")
        self.assertContains(member, 'href="/anket/yeni/"')
        self.assertContains(member, 'href="/anketlerim/"')


class ModelTests(TestCase):
    def test_option_position_unique_per_poll(self):
        from django.db import IntegrityError, transaction

        poll = make_poll(make_user())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Option.objects.create(poll=poll, text="Tekrar", position=0)
