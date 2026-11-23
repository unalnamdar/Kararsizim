import ipaddress
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from accounts import ratelimit
from accounts.models import RateLimitEvent

from .models import Poll, Report, Vote
from .test_voting import VoteTestCase
from .tests import make_poll, make_user
from .voting import MAX_VOTES_PER_IP

User = get_user_model()

IP_A = "203.0.113.7"
IP_B = "203.0.113.99"


def digest_of(ip):
    return ratelimit.ip_digest(ipaddress.ip_address(ip))


class IpVoteTestCase(VoteTestCase):
    def vote_from(self, ip, option=None, poll=None, client=None):
        poll = poll or self.poll
        option = option or poll.options.first()
        meta = {"HTTP_X_VERCEL_FORWARDED_FOR": ip} if ip else {}
        return (client or self.client_class()).post(
            f"/anket/{poll.pk}/oy/",
            data=json.dumps({"option_id": option.pk}),
            content_type="application/json",
            **meta,
        )


class IpDigestOnVotesTests(IpVoteTestCase):
    def test_vote_stores_the_ip_digest_never_the_ip(self):
        self.assertEqual(self.vote_from(IP_A).status_code, 200)
        vote = Vote.objects.get()
        self.assertEqual(vote.ip_hash, digest_of(IP_A))
        for value in (vote.ip_hash, vote.voter_key):
            self.assertNotIn(IP_A, value)

    def test_without_a_trusted_header_nothing_is_stored_or_limited(self):
        for _ in range(MAX_VOTES_PER_IP + 3):
            self.assertEqual(self.vote_from(None).status_code, 200)
        self.assertEqual(Vote.objects.filter(ip_hash__isnull=True).count(), MAX_VOTES_PER_IP + 3)


class PerNetworkCapTests(IpVoteTestCase):
    def test_five_votes_from_one_network_then_blocked(self):
        for _ in range(MAX_VOTES_PER_IP):
            self.assertEqual(self.vote_from(IP_A).status_code, 200)
        response = self.vote_from(IP_A)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(), {"error": "Bu ağdan bu ankete verilebilecek en fazla oy sayısına ulaşıldı."}
        )
        self.assertEqual(Vote.objects.count(), MAX_VOTES_PER_IP)

    def test_another_network_can_still_vote(self):
        for _ in range(MAX_VOTES_PER_IP):
            self.vote_from(IP_A)
        self.assertEqual(self.vote_from(IP_B).status_code, 200)

    def test_cap_is_per_poll(self):
        other = make_poll(self.owner, question="Başka soru")
        for _ in range(MAX_VOTES_PER_IP):
            self.vote_from(IP_A)
        self.assertEqual(self.vote_from(IP_A, poll=other).status_code, 200)

    def test_already_voted_beats_the_cap(self):
        first = self.client_class()
        self.vote_from(IP_A, client=first)
        for _ in range(MAX_VOTES_PER_IP - 1):
            self.vote_from(IP_A)
        # the network is full, but the first browser asking again is told it already voted
        response = self.vote_from(IP_A, option=self.coffee, client=first)
        self.assertEqual(response.status_code, 409)

    def test_members_count_towards_the_cap(self):
        for _ in range(MAX_VOTES_PER_IP - 1):
            self.vote_from(IP_A)
        member_client = self.client_class()
        member_client.force_login(make_user("uye"))
        self.assertEqual(self.vote_from(IP_A, client=member_client).status_code, 200)
        self.assertEqual(self.vote_from(IP_A).status_code, 403)

    def test_rejected_vote_creates_nothing_and_leaks_no_results(self):
        for _ in range(MAX_VOTES_PER_IP):
            self.vote_from(IP_A)
        body = self.vote_from(IP_A).json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(Vote.objects.count(), MAX_VOTES_PER_IP)

    def test_no_js_form_gets_a_message(self):
        for _ in range(MAX_VOTES_PER_IP):
            self.vote_from(IP_A)
        response = self.client_class().post(
            self.url, {"option_id": self.tea.pk}, HTTP_X_VERCEL_FORWARDED_FOR=IP_A, follow=True
        )
        self.assertContains(response, "Bu ağdan bu ankete verilebilecek en fazla oy sayısına ulaşıldı.")
        self.assertEqual(Vote.objects.count(), MAX_VOTES_PER_IP)


class VoteRateLimitTests(IpVoteTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(ratelimit.LIMITS, {"vote": (3, 60)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.polls = [self.poll] + [make_poll(self.owner, question=f"Soru {i}") for i in range(4)]

    def test_fourth_vote_in_a_minute_gets_429_with_retry_after(self):
        for poll in self.polls[:3]:
            self.assertEqual(self.vote_from(IP_A, poll=poll).status_code, 200)
        response = self.vote_from(IP_A, poll=self.polls[3])
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.json()["error"].startswith("Çok hızlı oy veriyorsun."))
        self.assertTrue(1 <= int(response["Retry-After"]) <= 60)
        self.assertEqual(Vote.objects.count(), 3)

    def test_other_networks_are_not_affected(self):
        for poll in self.polls[:3]:
            self.vote_from(IP_A, poll=poll)
        self.assertEqual(self.vote_from(IP_B, poll=self.polls[3]).status_code, 200)

    def test_failed_attempts_do_not_count(self):
        for _ in range(6):
            response = self.client_class().post(
                self.url, data=json.dumps({"option_id": 999999}), content_type="application/json",
                HTTP_X_VERCEL_FORWARDED_FOR=IP_A,
            )
            self.assertEqual(response.status_code, 400)
        for poll in self.polls[:3]:
            self.assertEqual(self.vote_from(IP_A, poll=poll).status_code, 200)

    def test_limit_lifts_after_the_window(self):
        for poll in self.polls[:3]:
            self.vote_from(IP_A, poll=poll)
        RateLimitEvent.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self.vote_from(IP_A, poll=self.polls[3]).status_code, 200)

    def test_no_js_form_gets_a_message(self):
        for poll in self.polls[:3]:
            self.vote_from(IP_A, poll=poll)
        response = self.client_class().post(
            f"/anket/{self.polls[3].pk}/oy/",
            {"option_id": self.polls[3].options.first().pk},
            HTTP_X_VERCEL_FORWARDED_FOR=IP_A,
            follow=True,
        )
        self.assertContains(response, "Çok hızlı oy veriyorsun.")
        self.assertEqual(Vote.objects.count(), 3)


class ReportTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")
        self.poll = make_poll(self.owner, question="Bildirilecek anket")
        self.url = f"/anket/{self.poll.pk}/bildir/"

    def report(self, reason="spam", note="", ip=None, client=None, **extra):
        meta = {"HTTP_X_VERCEL_FORWARDED_FOR": ip} if ip else {}
        return (client or self.client_class()).post(
            self.url, {"reason": reason, "note": note}, follow=True, **meta, **extra
        )

    def test_detail_shows_the_form_to_guests_and_other_members_but_not_the_owner(self):
        detail = f"/anket/{self.poll.pk}/"
        self.assertContains(self.client.get(detail), f'action="{self.url}"')
        self.client.force_login(make_user("baska"))
        self.assertContains(self.client.get(detail), f'action="{self.url}"')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(detail), f'action="{self.url}"')

    def test_guest_report_is_stored_with_an_ip_based_reporter(self):
        response = self.report(reason="abusive", note="  çok   rahatsız edici ", ip=IP_A)
        self.assertRedirects(response, f"/anket/{self.poll.pk}/")
        self.assertContains(response, "Bildirimin alındı. Teşekkürler.")
        report = Report.objects.get()
        self.assertEqual(report.reason, "abusive")
        self.assertEqual(report.note, "çok rahatsız edici")
        self.assertEqual(report.reporter, f"i{digest_of(IP_A)}")
        self.assertIsNone(report.user)
        self.assertNotIn(IP_A, report.reporter)

    def test_guest_without_a_trusted_ip_header_gets_a_shared_anonymous_key(self):
        self.report()
        self.assertEqual(Report.objects.get().reporter, "anon")

    def test_same_guest_network_cannot_report_twice_but_another_can(self):
        self.report(ip=IP_A)
        response = self.report(ip=IP_A)
        self.assertContains(response, "Bu anketi zaten bildirmiştin.")
        self.assertEqual(Report.objects.count(), 1)
        self.report(ip=IP_B)
        self.assertEqual(Report.objects.count(), 2)

    def test_member_report_is_tied_to_the_account(self):
        member = make_user("uye")
        client = self.client_class()
        client.force_login(member)
        self.report(client=client, ip=IP_A)
        report = Report.objects.get()
        self.assertEqual(report.reporter, f"u{member.pk}")
        self.assertEqual(report.user, member)
        self.assertContains(self.report(client=client, ip=IP_B), "Bu anketi zaten bildirmiştin.")
        self.assertEqual(Report.objects.count(), 1)

    def test_owner_cannot_report_own_poll(self):
        client = self.client_class()
        client.force_login(self.owner)
        self.assertContains(self.report(client=client), "Kendi anketini bildiremezsin.")
        self.assertFalse(Report.objects.exists())

    def test_invalid_input_is_rejected_with_a_message(self):
        cases = [
            ({"reason": "yok-boyle-neden"}, "Geçersiz bir neden seçtin."),
            ({"reason": ""}, "Bir neden seç."),
            ({"reason": "spam", "note": "x" * 201}, "Not en fazla 200 karakter olabilir."),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                response = self.client_class().post(self.url, data, follow=True)
                self.assertContains(response, message)
        self.assertFalse(Report.objects.exists())

    def test_only_post_and_csrf_protected(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        response = Client(enforce_csrf_checks=True).post(self.url, {"reason": "spam"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Report.objects.exists())

    def test_missing_poll_is_404(self):
        self.assertEqual(self.client.post("/anket/9999/bildir/", {"reason": "spam"}).status_code, 404)

    def test_report_rate_limit(self):
        polls = [make_poll(self.owner, question=f"Soru {i}") for i in range(3)]
        with mock.patch.dict(ratelimit.LIMITS, {"report": (2, 3600)}):
            for poll in polls[:2]:
                self.client_class().post(f"/anket/{poll.pk}/bildir/", {"reason": "spam"}, HTTP_X_VERCEL_FORWARDED_FOR=IP_A)
            response = self.client_class().post(
                f"/anket/{polls[2].pk}/bildir/", {"reason": "spam"}, HTTP_X_VERCEL_FORWARDED_FOR=IP_A, follow=True
            )
        self.assertContains(response, "Çok fazla bildirim gönderdin.")
        self.assertEqual(Report.objects.count(), 2)

    def test_deleting_the_poll_deletes_its_reports(self):
        self.report(ip=IP_A)
        self.poll.delete()
        self.assertFalse(Report.objects.exists())

    def test_reports_never_appear_on_public_pages(self):
        self.report(reason="abusive", note="gizli not", ip=IP_A)
        for url in ["/", f"/anket/{self.poll.pk}/"]:
            html = self.client.get(url).content.decode()
            self.assertNotIn("gizli not", html)
        self.client.force_login(self.owner)
        self.assertNotIn("gizli not", self.client.get(f"/anket/{self.poll.pk}/").content.decode())
        self.assertNotIn("gizli not", self.client.get("/anketlerim/").content.decode())


class ReportAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", username="yonetici", password="x")
        self.poll = make_poll(make_user("sahip"), question="Şikâyetli anket")
        Report.objects.create(poll=self.poll, reporter="i1", reason="spam", note="reklam yapıyor")
        Report.objects.create(poll=self.poll, reporter="i2", reason="abusive")
        make_poll(make_user("temiz"), question="Temiz anket")

    def test_staff_sees_reports_and_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/polls/report/")
        self.assertContains(response, "reklam yapıyor")
        self.assertContains(response, "misafir")

        polls = {p.question: p._reports for p in self.client.get("/admin/polls/poll/").context["cl"].result_list}
        self.assertEqual(polls, {"Şikâyetli anket": 2, "Temiz anket": 0})

    def test_poll_admin_page_lists_its_reports(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/admin/polls/poll/{self.poll.pk}/change/")
        self.assertContains(response, "reklam yapıyor")

    def test_regular_members_cannot_open_the_admin(self):
        self.client.force_login(make_user("uye"))
        self.assertEqual(self.client.get("/admin/polls/report/").status_code, 302)
