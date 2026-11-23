import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from . import ratelimit
from .models import RateLimitEvent

User = get_user_model()

OLD_PASSWORD = "eski-Parola#47x"
NEW_PASSWORD = "yeni-Parola#92q"
IP_A = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.7"}
IP_B = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.99"}

REQUEST_URL = "/parola-sifirla/"
SENT_URL = "/parola-sifirla/gonderildi/"
DONE_URL = "/parola-sifirla/tamam/"


@override_settings(PASSWORD_RESET_ENABLED=True)
class ResetTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ayse@example.com", username="ayse", password=OLD_PASSWORD)

    def request_reset(self, email="ayse@example.com", client=None, **meta):
        return (client or self.client_class()).post(REQUEST_URL, {"email": email}, **meta)

    def reset_link(self):
        """The path of the confirmation link in the (single) email that was sent."""
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"https?://[^/\s]+(/parola-sifirla/[^\s]+/)", mail.outbox[0].body)
        self.assertIsNotNone(match, mail.outbox[0].body)
        return match.group(1)


class FeatureSwitchTests(TestCase):
    URLS = [REQUEST_URL, SENT_URL, DONE_URL, "/parola-sifirla/abc/def-123/"]

    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_everything_is_404_and_the_link_is_hidden_when_disabled(self):
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(REQUEST_URL, {"email": "a@b.co"}).status_code, 404)
        self.assertNotContains(self.client.get("/giris/"), "Parolanı mı unuttun?")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(PASSWORD_RESET_ENABLED=True)
    def test_link_is_shown_and_pages_open_when_enabled(self):
        self.assertContains(self.client.get("/giris/"), f'href="{REQUEST_URL}">Parolanı mı unuttun?')
        for url in (REQUEST_URL, SENT_URL, DONE_URL):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class RequestTests(ResetTestCase):
    def test_form_page(self):
        response = self.client.get(REQUEST_URL)
        self.assertContains(response, "<title>Parolanı sıfırla · Kararsızım</title>", html=False)
        self.assertContains(response, 'name="email"')

    def test_known_address_gets_one_email_with_a_working_link(self):
        response = self.request_reset(**IP_A)
        self.assertRedirects(response, SENT_URL)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ayse@example.com"])
        self.assertEqual(message.subject, "Kararsızım: parolanı sıfırla")
        self.assertIn("@ayse", message.body)
        self.assertIn("1 saat", message.body)
        self.assertRegex(message.body, r"http://testserver/parola-sifirla/[\w-]+/[\w-]+/")

    def test_unknown_address_gets_the_same_answer_but_no_email(self):
        known = self.request_reset(**IP_A)
        unknown = self.request_reset("kimse@example.com", **IP_A)
        self.assertEqual((known.status_code, known["Location"]), (unknown.status_code, unknown["Location"]))
        self.assertEqual(len(mail.outbox), 1)  # only the known address
        sent_page = self.client.get(SENT_URL).content
        self.assertIn("Bu adrese bağlı bir hesap varsa".encode(), sent_page)

    def test_address_match_ignores_case(self):
        self.request_reset("AYSE@Example.COM")
        self.assertEqual(len(mail.outbox), 1)

    def test_inactive_accounts_get_no_email(self):
        self.user.is_active = False
        self.user.save()
        self.assertRedirects(self.request_reset(), SENT_URL)
        self.assertEqual(len(mail.outbox), 0)

    def test_malformed_address_shows_the_error_summary(self):
        response = self.request_reset("bu-bir-adres-degil")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-error-summary")
        self.assertContains(response, "Geçerli bir e-posta adresi gir.")
        self.assertEqual(len(mail.outbox), 0)

    def test_email_is_not_in_the_sent_page(self):
        self.request_reset()
        self.assertNotContains(self.client.get(SENT_URL), "ayse@example.com")


class RateLimitTests(ResetTestCase):
    def test_per_ip_limit_counts_known_and_unknown_addresses_alike(self):
        with mock.patch.dict(ratelimit.LIMITS, {"password_reset": (2, 3600)}):
            self.request_reset("kimse1@example.com", **IP_A)
            self.request_reset("kimse2@example.com", **IP_A)  # unknown addresses use up the allowance too
            response = self.request_reset(**IP_A)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Kısa sürede çok fazla istek yaptın.", status_code=429)
        self.assertGreaterEqual(int(response["Retry-After"]), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_other_networks_are_not_affected(self):
        with mock.patch.dict(ratelimit.LIMITS, {"password_reset": (1, 3600)}):
            self.request_reset(**IP_A)
            self.assertEqual(self.request_reset(**IP_B).status_code, 302)

    def test_per_address_limit_silently_skips_the_email(self):
        with mock.patch.dict(ratelimit.LIMITS, {"password_reset_email": (1, 3600)}):
            first = self.request_reset(**IP_A)
            second = self.request_reset(**IP_B)
            other = User.objects.create_user(email="can@example.com", username="can", password=OLD_PASSWORD)
            third = self.request_reset("can@example.com", **IP_B)
        self.assertEqual(first["Location"], second["Location"])  # same page, nothing reveals the limit
        self.assertEqual([m.to for m in mail.outbox], [["ayse@example.com"], ["can@example.com"]])
        self.assertIsNotNone(other)
        self.assertEqual(third.status_code, 302)

    def test_limit_lifts_after_the_window(self):
        with mock.patch.dict(ratelimit.LIMITS, {"password_reset": (1, 3600)}):
            self.request_reset(**IP_A)
            RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(hours=2))
            self.assertEqual(self.request_reset(**IP_A).status_code, 302)

    def test_no_raw_address_is_stored_for_rate_limiting(self):
        self.request_reset(**IP_A)
        for event in RateLimitEvent.objects.all():
            self.assertNotIn("ayse", event.key)
            self.assertNotIn("example.com", event.key)


class ConfirmTests(ResetTestCase):
    def open_form(self, client=None):
        client = client or self.client
        self.request_reset(client=client)
        link = self.reset_link()
        response = client.get(link, follow=True)  # Django swaps the token for "set-password" in the address
        return client, response

    def test_full_flow_changes_the_password_and_does_not_log_in(self):
        client, response = self.open_form()
        self.assertContains(response, "Yeni parola belirle")
        set_url = response.redirect_chain[-1][0]
        done = client.post(set_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        self.assertRedirects(done, DONE_URL)
        self.assertNotIn("_auth_user_id", client.session)  # no automatic login
        self.assertContains(client.get(DONE_URL), "Parolan değişti")

        self.assertFalse(self.client_class().login(email="ayse@example.com", password=OLD_PASSWORD))
        self.assertTrue(self.client_class().login(email="ayse@example.com", password=NEW_PASSWORD))

    def test_the_link_works_only_once(self):
        client, response = self.open_form()
        link = self.reset_link()
        client.post(response.redirect_chain[-1][0], {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        again = self.client_class().get(link, follow=True)
        self.assertContains(again, "Bağlantı geçersiz")
        self.assertContains(again, f'href="{REQUEST_URL}"')

    def test_tampered_token_is_rejected(self):
        self.request_reset()
        link = self.reset_link()
        tampered = link[:-2] + ("a" if link[-2] != "a" else "b") + "/"
        response = self.client_class().get(tampered, follow=True)
        self.assertContains(response, "Bağlantı geçersiz")

    @override_settings(PASSWORD_RESET_TIMEOUT=-1)
    def test_expired_token_is_rejected(self):
        self.request_reset()
        response = self.client_class().get(self.reset_link(), follow=True)
        self.assertContains(response, "Bağlantı geçersiz")

    def test_link_lifetime_is_one_hour(self):
        from django.conf import settings

        self.assertEqual(settings.PASSWORD_RESET_TIMEOUT, 3600)

    def test_weak_and_mismatched_passwords_are_rejected(self):
        client, response = self.open_form()
        set_url = response.redirect_chain[-1][0]
        cases = {
            ("kisa1", "kisa1"): "password",
            ("12345678901", "12345678901"): "password",
            (NEW_PASSWORD, "baska-Parola#11z"): "Parolalar birbiriyle eşleşmiyor.",
        }
        for (first, second), expected in cases.items():
            with self.subTest(first=first, second=second):
                result = client.post(set_url, {"new_password1": first, "new_password2": second})
                self.assertEqual(result.status_code, 200)
                self.assertContains(result, "data-error-summary")
                if expected == "password":
                    self.assertIn("new_password1", result.context["form"].errors)  # the weak one is blamed
                    self.assertNotIn("new_password2", result.context["form"].errors)
                else:
                    self.assertContains(result, expected)
                    self.assertIn("new_password2", result.context["form"].errors)
        self.assertTrue(User.objects.get().check_password(OLD_PASSWORD))

    def test_other_sessions_are_logged_out_after_a_reset(self):
        other_device = self.client_class()
        other_device.force_login(self.user)
        self.assertEqual(other_device.get("/anketlerim/").status_code, 200)

        client, response = self.open_form()
        client.post(response.redirect_chain[-1][0], {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        self.assertEqual(other_device.get("/anketlerim/").status_code, 302)

    def test_invalid_link_page_has_no_form(self):
        response = self.client.get("/parola-sifirla/abc/def-123/", follow=True)
        self.assertContains(response, "Bağlantı geçersiz")
        self.assertNotContains(response, 'name="new_password1"')


class MarkupTests(ResetTestCase):
    def test_no_dangling_aria_references_and_error_summary_gets_the_focus_script(self):
        from config.test_design import dangling_references

        failed_request = self.request_reset("bu-bir-adres-degil")
        self.request_reset()
        client = self.client_class()
        client.get(self.reset_link())  # primes the session token
        confirm = client.get(self.reset_link(), follow=True)
        failed_confirm = client.post(
            confirm.redirect_chain[-1][0], {"new_password1": "a", "new_password2": "b"}
        )
        for name, response in {"request": failed_request, "confirm": failed_confirm}.items():
            with self.subTest(page=name):
                html = response.content.decode()
                self.assertEqual(dangling_references(html), [])
                self.assertIn("data-error-summary", html)
                self.assertNotIn("autofocus", html)  # nothing may compete with the summary for focus
