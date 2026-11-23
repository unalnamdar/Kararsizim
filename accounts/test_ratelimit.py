import ipaddress
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import ratelimit
from .models import RateLimitEvent

User = get_user_model()
STRONG_PASSWORD = "g8#kLq!29zPa"


def digest_of(text):
    return ratelimit.ip_digest(ipaddress.ip_address(text))


class ClientIpTests(SimpleTestCase):
    def ip(self, **meta):
        return ratelimit.client_ip(RequestFactory().get("/", **meta))

    def test_vercel_header_wins(self):
        ip = self.ip(HTTP_X_VERCEL_FORWARDED_FOR="203.0.113.7", HTTP_X_FORWARDED_FOR="198.51.100.1")
        self.assertEqual(str(ip), "203.0.113.7")

    def test_x_forwarded_for_fallback_uses_first_entry_only(self):
        ip = self.ip(HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1, 10.0.0.2")
        self.assertEqual(str(ip), "203.0.113.9")

    def test_remote_addr_is_ignored(self):
        """Behind Vercel REMOTE_ADDR is shared infrastructure; trusting it would make per-IP limits global."""
        self.assertIsNone(self.ip(REMOTE_ADDR="127.0.0.1"))
        self.assertIsNone(self.ip())

    def test_garbage_is_ignored(self):
        for value in ["not-an-ip", "999.1.1.1", "  ", ","]:
            with self.subTest(value=value):
                self.assertIsNone(self.ip(HTTP_X_VERCEL_FORWARDED_FOR=value))

    def test_ipv6(self):
        self.assertEqual(self.ip(HTTP_X_VERCEL_FORWARDED_FOR="2001:db8::1").version, 6)


class IpDigestTests(SimpleTestCase):
    def test_deterministic_and_distinct(self):
        self.assertEqual(digest_of("203.0.113.7"), digest_of("203.0.113.7"))
        self.assertNotEqual(digest_of("203.0.113.7"), digest_of("203.0.113.8"))

    def test_shape_and_no_raw_ip(self):
        digest = digest_of("203.0.113.7")
        self.assertRegex(digest, r"^[0-9a-f]{32}$")
        self.assertNotIn("203.0.113.7", digest)
        self.assertEqual(len(digest), 32)  # a truncated HMAC, not the address in disguise

    def test_unknown_ip_has_no_digest(self):
        self.assertIsNone(ratelimit.ip_digest(None))

    def test_digest_is_keyed_by_secret_key(self):
        before = digest_of("203.0.113.7")
        with override_settings(SECRET_KEY="another-secret-key-" + "z" * 40):
            after = digest_of("203.0.113.7")
        self.assertNotEqual(before, after)

    def test_ipv6_addresses_in_the_same_64_share_a_digest(self):
        self.assertEqual(digest_of("2001:db8:1:2::1"), digest_of("2001:db8:1:2:ffff::9"))
        self.assertNotEqual(digest_of("2001:db8:1:2::1"), digest_of("2001:db8:1:3::1"))

    def test_ipv4_mapped_ipv6_matches_ipv4(self):
        self.assertEqual(digest_of("::ffff:203.0.113.7"), digest_of("203.0.113.7"))


class EmailDigestTests(SimpleTestCase):
    def test_case_and_whitespace_do_not_matter(self):
        self.assertEqual(ratelimit.email_digest(" Ayse@Example.com "), ratelimit.email_digest("ayse@example.com"))

    def test_distinct_addresses_differ_and_no_address_is_left_in_the_digest(self):
        digest = ratelimit.email_digest("ayse@example.com")
        self.assertNotEqual(digest, ratelimit.email_digest("can@example.com"))
        self.assertRegex(digest, r"^[0-9a-f]{32}$")
        self.assertNotIn("ayse", digest)

    def test_empty_input_has_no_digest(self):
        self.assertIsNone(ratelimit.email_digest(""))
        self.assertIsNone(ratelimit.email_digest(None))

    def test_digest_is_keyed_by_secret_key(self):
        before = ratelimit.email_digest("ayse@example.com")
        with override_settings(SECRET_KEY="another-secret-key-" + "z" * 40):
            after = ratelimit.email_digest("ayse@example.com")
        self.assertNotEqual(before, after)


class LimiterTests(TestCase):
    def setUp(self):
        patcher = mock.patch.dict(ratelimit.LIMITS, {"vote": (3, 60), "signup": (2, 3600), "report": (1, 3600)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_allows_until_the_limit_then_blocks_with_a_wait(self):
        for _ in range(3):
            self.assertIsNone(ratelimit.check("vote", "k1"))
            ratelimit.record("vote", "k1")
        wait = ratelimit.check("vote", "k1")
        self.assertIsNotNone(wait)
        self.assertTrue(1 <= wait <= 60)

    def test_keys_and_scopes_are_independent(self):
        for _ in range(3):
            ratelimit.record("vote", "k1")
        self.assertIsNotNone(ratelimit.check("vote", "k1"))
        self.assertIsNone(ratelimit.check("vote", "k2"))
        self.assertIsNone(ratelimit.check("signup", "k1"))

    def test_missing_key_is_never_limited_or_recorded(self):
        ratelimit.record("vote", None)
        self.assertFalse(RateLimitEvent.objects.exists())
        self.assertIsNone(ratelimit.check("vote", None))

    def test_events_expire(self):
        for _ in range(3):
            ratelimit.record("vote", "k1")
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        self.assertIsNone(ratelimit.check("vote", "k1"))

    def test_wait_shrinks_as_the_oldest_event_ages(self):
        for _ in range(3):
            ratelimit.record("vote", "k1")
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(seconds=50))
        self.assertLessEqual(ratelimit.check("vote", "k1"), 10)

    def test_old_rows_are_pruned(self):
        ratelimit.record("vote", "old")
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(days=2))
        with mock.patch("accounts.ratelimit.random.random", return_value=0.0):
            ratelimit.record("vote", "new")
        self.assertEqual(list(RateLimitEvent.objects.values_list("key", flat=True)), ["new"])

    def test_human_wait(self):
        self.assertEqual(ratelimit.human_wait(12), "12 saniye")
        self.assertEqual(ratelimit.human_wait(89), "89 saniye")
        self.assertEqual(ratelimit.human_wait(300), "5 dakika")
        self.assertEqual(ratelimit.human_wait(3600), "60 dakika")


class SignupLimitTests(TestCase):
    def setUp(self):
        patcher = mock.patch.dict(ratelimit.LIMITS, {"signup": (2, 3600)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def signup(self, n, ip="203.0.113.7", client=None, **overrides):
        data = {
            "email": f"kisi{n}@example.com",
            "username": f"kisi{n}",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD,
        }
        data.update(overrides)
        extra = {"HTTP_X_VERCEL_FORWARDED_FOR": ip} if ip else {}
        return (client or self.client_class()).post("/kayit/", data, **extra)

    def test_third_account_from_one_ip_is_blocked(self):
        self.assertEqual(self.signup(1).status_code, 302)
        self.assertEqual(self.signup(2).status_code, 302)
        response = self.signup(3)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Bu ağdan kısa sürede çok sayıda hesap açıldı.", status_code=429)
        self.assertTrue(int(response["Retry-After"]) >= 1)
        self.assertFalse(User.objects.filter(username="kisi3").exists())

    def test_blocked_page_uses_the_error_summary(self):
        self.signup(1), self.signup(2)
        response = self.signup(3)
        self.assertContains(response, "data-error-summary", status_code=429)

    def test_other_ips_are_not_affected(self):
        self.signup(1), self.signup(2)
        self.assertEqual(self.signup(3, ip="203.0.113.99").status_code, 302)

    def test_failed_validation_does_not_count(self):
        for _ in range(6):
            self.assertEqual(self.signup(1, username="ab").status_code, 200)  # username too short
        self.assertEqual(self.signup(1).status_code, 302)

    def test_no_trusted_ip_header_means_no_limit(self):
        for n in range(1, 5):
            self.assertEqual(self.signup(n, ip=None).status_code, 302)

    def test_limit_lifts_after_the_window(self):
        self.signup(1), self.signup(2)
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.signup(3).status_code, 302)
