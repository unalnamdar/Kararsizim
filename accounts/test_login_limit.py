from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from . import ratelimit
from .models import RateLimitEvent

User = get_user_model()

PASSWORD = "g8#kLq!29zPa"
IP_A = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.7"}
IP_B = {"HTTP_X_VERCEL_FORWARDED_FOR": "203.0.113.99"}
LOCKED = "Çok fazla başarısız giriş denemesi."


class LoginLimitTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ayse@example.com", username="ayse", password=PASSWORD)
        patcher = mock.patch.dict(ratelimit.LIMITS, {"login": (3, 900)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def attempt(self, password="wrong-password", client=None, email="ayse@example.com", **meta):
        return (client or self.client).post("/giris/", {"username": email, "password": password}, **meta)


class LoginLimitTests(LoginLimitTestCase):
    def test_failed_attempts_are_blocked_after_the_limit(self):
        for _ in range(3):
            self.assertEqual(self.attempt(**IP_A).status_code, 200)  # normal "wrong password" page
        response = self.attempt(**IP_A)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, LOCKED, status_code=429)
        self.assertContains(response, "data-error-summary", status_code=429)
        self.assertGreaterEqual(int(response["Retry-After"]), 1)

    def test_the_right_password_is_refused_while_locked_out(self):
        for _ in range(3):
            self.attempt(**IP_A)
        response = self.attempt(PASSWORD, **IP_A)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_typed_address_survives_the_lockout_page(self):
        for _ in range(3):
            self.attempt(**IP_A)
        self.assertContains(self.attempt(**IP_A), 'value="ayse@example.com"', status_code=429)

    def test_other_networks_are_not_affected(self):
        for _ in range(4):
            self.attempt(**IP_A)
        response = self.attempt(PASSWORD, client=self.client_class(), **IP_B)
        self.assertEqual(response.status_code, 302)

    def test_guessing_other_addresses_counts_towards_the_same_network_limit(self):
        for n in range(3):
            self.attempt(email=f"kimse{n}@example.com", **IP_A)
        self.assertEqual(self.attempt(**IP_A).status_code, 429)

    def test_successful_logins_do_not_use_up_the_allowance(self):
        """Classmates on one Wi-Fi sign in all day; only failures count."""
        for _ in range(2):  # limit is 3: two failures leave room, and each sign-in in between is free
            self.assertEqual(self.attempt(**IP_A).status_code, 200)
            self.assertEqual(self.attempt(PASSWORD, client=self.client_class(), **IP_A).status_code, 302)
        self.assertEqual(self.attempt(PASSWORD, client=self.client_class(), **IP_A).status_code, 302)
        self.assertEqual(RateLimitEvent.objects.filter(scope="login").count(), 2)  # the two failures only

    def test_no_trusted_ip_header_means_no_limit(self):
        for _ in range(6):
            self.assertEqual(self.attempt().status_code, 200)
        self.assertEqual(self.attempt(PASSWORD).status_code, 302)

    def test_limit_lifts_after_the_window(self):
        for _ in range(3):
            self.attempt(**IP_A)
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.attempt(PASSWORD, **IP_A).status_code, 302)

    def test_malformed_address_is_a_field_error_and_costs_nothing(self):
        """A typo in the address never reaches the password check, so it is not a guess."""
        for _ in range(5):
            self.assertEqual(self.attempt(email="not-an-address", **IP_A).status_code, 200)
        self.assertFalse(RateLimitEvent.objects.filter(scope="login").exists())
        self.assertEqual(self.attempt(PASSWORD, **IP_A).status_code, 302)

    def test_events_hold_only_a_keyed_digest(self):
        self.attempt(**IP_A)
        event = RateLimitEvent.objects.get(scope="login")
        self.assertRegex(event.key, r"^[0-9a-f]{32}$")
        self.assertNotIn("203.0.113", event.key)


class ReserveTests(TestCase):
    """reserve() counts the attempt first and checks second, so a burst of parallel requests cannot all slip through."""

    def setUp(self):
        patcher = mock.patch.dict(ratelimit.LIMITS, {"login": (3, 900)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_allows_up_to_the_limit_then_denies_and_forgets_the_denied_attempt(self):
        for _ in range(3):
            wait, event = ratelimit.reserve("login", "k1")
            self.assertIsNone(wait)
            self.assertIsNotNone(event)
        wait, event = ratelimit.reserve("login", "k1")
        self.assertGreaterEqual(wait, 1)
        self.assertIsNone(event)
        self.assertEqual(RateLimitEvent.objects.filter(key="k1").count(), 3)  # denied tries do not extend the lockout

    def test_missing_key_is_never_limited_or_recorded(self):
        self.assertEqual(ratelimit.reserve("login", None), (None, None))
        self.assertFalse(RateLimitEvent.objects.exists())

    def test_counts_the_attempt_before_looking_at_the_total(self):
        """The property that makes it race-safe: by the time the total is read, this attempt is already in it."""
        seen = []
        original = RateLimitEvent.objects.filter  # captured before patching, or the spy would call itself

        def spy(*args, **kwargs):
            seen.append(original(key="k2").count())
            return original(*args, **kwargs)

        with mock.patch.object(RateLimitEvent.objects, "filter", side_effect=spy):
            ratelimit.reserve("login", "k2")
        self.assertEqual(seen[0], 1)


class AdminLoginLimitTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="root@example.com", username="root", password=PASSWORD)
        patcher = mock.patch.dict(ratelimit.LIMITS, {"login": (3, 900)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def attempt(self, password="wrong-password", **meta):
        return self.client.post(
            "/admin/login/", {"username": "root@example.com", "password": password, "next": "/admin/"}, **meta
        )

    def test_the_admin_login_shares_the_limit(self):
        for _ in range(3):
            self.assertNotContains(self.attempt(**IP_A), LOCKED)
        self.assertContains(self.attempt(**IP_A), LOCKED)

    def test_the_right_password_is_refused_while_locked_out(self):
        for _ in range(3):
            self.attempt(**IP_A)
        response = self.attempt(PASSWORD, **IP_A)
        self.assertContains(response, LOCKED)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_still_works_normally(self):
        response = self.attempt(PASSWORD, **IP_A)
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
