"""Phase 4 checks: design tokens (contrast, no stray colors), error pages, Open Graph, page shell."""

import re
import struct
from pathlib import Path
from unittest import mock

from django.contrib.staticfiles import finders
from django.test import Client, TestCase

from polls.models import Vote
from polls.tests import PASSWORD, make_poll, make_user

BASE_DIR = Path(__file__).resolve().parent.parent
TOKENS_CSS = (BASE_DIR / "static/css/tokens.css").read_text(encoding="utf-8")
MAIN_CSS = (BASE_DIR / "static/css/main.css").read_text(encoding="utf-8")


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def load_tokens():
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", strip_comments(TOKENS_CSS)))


def luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted([luminance(a), luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ContrastTests(TestCase):
    """WCAG 2.x AA: 4.5:1 for text, 3:1 for the borders and focus ring of UI components."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.t = load_tokens()

    def assert_pairs(self, pairs, minimum):
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                ratio = contrast(self.t[foreground], self.t[background])
                self.assertGreaterEqual(ratio, minimum, f"{foreground} on {background}: {ratio:.2f}:1 < {minimum}:1")

    def test_text_contrast(self):
        pairs = [
            ("color-text", "color-bg"), ("color-text", "color-surface"),
            ("color-text-muted", "color-bg"), ("color-text-muted", "color-surface"),
            ("color-on-primary", "color-primary"), ("color-on-primary", "color-primary-dark"),
            ("color-primary-dark", "color-bg"), ("color-primary-dark", "color-surface"),
            ("color-primary-dark", "color-primary-soft"), ("color-primary-dark", "opt-0-fill"),
            ("color-surface", "color-text"),  # skip link
            ("color-on-primary", "color-danger"), ("color-on-primary", "color-danger-dark"),
            ("color-danger", "color-surface"), ("color-danger", "color-danger-soft"),
            ("color-success", "color-success-soft"), ("color-warning", "color-warning-soft"),
            ("color-info", "color-info-soft"),
            # message icon glyph sits on the accent color
            ("color-surface", "color-info"), ("color-surface", "color-success"),
            ("color-surface", "color-warning"), ("color-surface", "color-danger"),
        ]
        self.assert_pairs(pairs, 4.5)

    def test_option_text_contrast(self):
        pairs = []
        for i in range(5):
            pairs += [
                (f"opt-{i}-strong", f"opt-{i}-soft"),
                (f"opt-{i}-strong", f"opt-{i}-fill"),
                (f"opt-{i}-strong", "color-surface"),
                ("color-text", f"opt-{i}-soft"),
            ]
        self.assert_pairs(pairs, 4.5)

    def test_component_boundaries_and_focus_ring(self):
        pairs = [("color-field-border", "color-surface"), ("color-field-border", "color-bg")]
        for i in range(5):
            pairs += [(f"opt-{i}-base", "color-surface"), (f"opt-{i}-base", "color-bg")]
        for background in ["color-bg", "color-surface", "color-primary-soft"] + [f"opt-{i}-soft" for i in range(5)]:
            pairs.append(("color-focus", background))
        self.assert_pairs(pairs, 3.0)


class TokenDisciplineTests(TestCase):
    COLOR_PROPERTIES = (
        "color", "background", "background-color", "border", "border-color", "border-top", "border-right",
        "border-bottom", "border-left", "outline", "outline-color", "box-shadow", "fill", "stroke",
        "text-decoration-color", "caret-color", "accent-color",
    )
    NAMED_COLORS = {
        "white", "black", "red", "blue", "green", "yellow", "orange", "purple", "pink", "gray", "grey", "silver",
        "gold", "navy", "teal", "coral", "maroon", "lime", "aqua", "cyan", "magenta", "brown", "indigo", "violet",
    }

    def test_main_css_has_no_raw_colors(self):
        css = strip_comments(MAIN_CSS)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css), [])
        self.assertEqual(re.findall(r"\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)a?\(", css), [])

        offenders = []
        for prop, value in re.findall(r"([a-z-]+)\s*:\s*([^;{}]+);", css):
            if prop not in self.COLOR_PROPERTIES:
                continue
            words = set(re.findall(r"[a-z]+", re.sub(r"var\([^)]*\)", "", value.lower())))
            offenders += [f"{prop}: {value.strip()}" for _ in [0] if words & self.NAMED_COLORS]
        self.assertEqual(offenders, [])

    def test_every_variable_used_in_main_css_is_defined(self):
        css = strip_comments(MAIN_CSS)
        used = set(re.findall(r"var\(\s*(--[\w-]+)", css))
        defined = set(re.findall(r"(--[\w-]+)\s*:", strip_comments(TOKENS_CSS))) | set(re.findall(r"(--[\w-]+)\s*:", css))
        self.assertEqual(sorted(used - defined), [])

    def test_templates_and_scripts_have_no_inline_colors(self):
        for path in list((BASE_DIR / "templates").rglob("*.html")) + list((BASE_DIR / "static/js").glob("*.js")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", text), [])
                self.assertEqual(re.findall(r"\.style\.(?!width\b)\w+", text), [])
                for style in re.findall(r'style="([^"]*)"', text):
                    self.assertRegex(style, r"^width:\s*\{\{[^}]+\}\}%;?$")


class TemplateHygieneTests(TestCase):
    def test_single_line_comments_are_closed_on_the_same_line(self):
        """`{# ... #}` only works on one line; a multi-line one leaks its text into the page."""
        offenders = []
        for path in (BASE_DIR / "templates").rglob("*.html"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "{#" in line and "#}" not in line.split("{#", 1)[1]:
                    offenders.append(f"{path.relative_to(BASE_DIR)}:{number}")
        self.assertEqual(offenders, [])

    def test_no_template_syntax_leaks_into_rendered_pages(self):
        owner = make_user("sahip")
        poll = make_poll(owner)
        pages = ["/", f"/anket/{poll.pk}/", "/giris/", "/kayit/", "/yok/"]
        for logged_in in (False, True):
            if logged_in:
                self.client.force_login(owner)
            for url in pages + (["/anketlerim/", "/anket/yeni/"] if logged_in else []):
                with self.subTest(url=url, logged_in=logged_in):
                    html = self.client.get(url).content.decode()
                    for token in ("{#", "#}", "{%", "%}", "{{", "}}"):
                        self.assertNotIn(token, html)


class ErrorPageTests(TestCase):
    def test_404_page(self):
        response = self.client.get("/boyle/bir/sayfa/yok/")
        self.assertContains(response, "Sayfa bulunamadı", status_code=404)
        self.assertContains(response, "Ana sayfaya dön", status_code=404)
        self.assertContains(response, 'class="logo"', status_code=404)  # still inside the site layout

    def test_missing_poll_uses_404_page(self):
        self.assertContains(self.client.get("/anket/9999/"), "Sayfa bulunamadı", status_code=404)

    def test_403_page_for_non_owner_delete(self):
        poll = make_poll(make_user("sahip"))
        self.client.force_login(make_user("baska"))
        response = self.client.post(f"/anket/{poll.pk}/sil/")
        self.assertContains(response, "Bu işlem için yetkin yok", status_code=403)
        self.assertContains(response, "Bu anketi yalnızca sahibi silebilir.", status_code=403)

    def test_csrf_failure_page(self):
        response = Client(enforce_csrf_checks=True).post("/giris/", {"username": "a@b.co", "password": "x"})
        self.assertContains(response, "Oturumun zaman aşımına uğradı", status_code=403)

    def test_500_page_is_standalone_and_turkish(self):
        client = Client(raise_request_exception=False)
        with mock.patch("polls.views.render", side_effect=RuntimeError("boom")), self.assertLogs("django.request", "ERROR"):
            response = client.get("/")
        self.assertContains(response, "Bir şeyler ters gitti", status_code=500)
        self.assertContains(response, "Ana sayfaya dön", status_code=500)
        self.assertNotContains(response, "boom", status_code=500)


class OpenGraphTests(TestCase):
    def setUp(self):
        self.owner = make_user("sahip")

    def test_detail_page_has_share_tags(self):
        poll = make_poll(self.owner, question='Dağ mı "deniz" mi?', options=("Dağ", "Deniz"))
        html = self.client.get(poll.get_absolute_url()).content.decode()
        self.assertIn('<meta property="og:title" content="Dağ mı &quot;deniz&quot; mi?">', html)
        self.assertIn('<meta property="og:description" content="Dağ · Deniz — Oy ver, sonuçları gör.">', html)
        self.assertIn(f'<meta property="og:url" content="http://testserver/anket/{poll.pk}/">', html)
        self.assertIn('<meta property="og:image" content="http://testserver/static/img/og-image.png">', html)
        self.assertIn('<meta name="description" content="Dağ · Deniz — Oy ver, sonuçları gör.">', html)
        self.assertIn('<meta property="og:locale" content="tr_TR">', html)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', html)

    def test_preview_never_leaks_results(self):
        poll = make_poll(self.owner, options=("Çay", "Kahve"))
        Vote.objects.create(poll=poll, option=poll.options.first(), voter_key="00000000-0000-4000-8000-000000000001")
        expected = '<meta property="og:description" content="Çay · Kahve — Oy ver, sonuçları gör.">'

        self.assertIn(expected, self.client.get(poll.get_absolute_url()).content.decode())  # guest
        self.client.force_login(self.owner)
        self.assertIn(expected, self.client.get(poll.get_absolute_url()).content.decode())  # owner sees results

    def test_question_is_escaped_in_head(self):
        poll = make_poll(self.owner, question="<script>alert(1)</script>")
        html = self.client.get(poll.get_absolute_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_long_options_are_truncated(self):
        poll = make_poll(self.owner, options=tuple(chr(65 + i) * 80 for i in range(5)))
        html = self.client.get(poll.get_absolute_url()).content.decode()
        description = re.search(r'<meta property="og:description" content="([^"]*)">', html).group(1)
        self.assertLessEqual(len(description), 150 + len(" — Oy ver, sonuçları gör."))
        self.assertIn("…", description)

    def test_feed_has_site_level_tags(self):
        html = self.client.get("/").content.decode()
        self.assertIn('<meta property="og:title" content="Kararsızım">', html)
        self.assertIn('<meta property="og:url" content="http://testserver/">', html)


class PageShellTests(TestCase):
    def test_head_and_landmarks(self):
        html = self.client.get("/").content.decode()
        self.assertIn('<html lang="tr">', html)
        self.assertIn('name="viewport"', html)
        self.assertIn('rel="icon" href="/static/img/favicon.svg"', html)
        self.assertIn("family=Plus+Jakarta+Sans", html)
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertIn('id="main"', html)

    def test_favicon_ico_redirects_to_svg(self):
        response = self.client.get("/favicon.ico")
        self.assertRedirects(response, "/static/img/favicon.svg", status_code=301, fetch_redirect_response=False)

    def test_static_assets_exist(self):
        for name in ["css/tokens.css", "css/main.css", "js/vote.js", "js/poll-form.js", "js/site.js", "img/favicon.svg"]:
            with self.subTest(asset=name):
                self.assertIsNotNone(finders.find(name))

    def test_og_image_is_1200_by_630_png(self):
        data = Path(finders.find("img/og-image.png")).read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630))

    def test_page_titles(self):
        member = make_user("uye")
        poll = make_poll(make_user("yazar"), question="Çay mı kahve mi?")
        expected = {
            "/": "Kararsızım · Kararsız kalınca topluluğa sor",
            "/giris/": "Giriş yap · Kararsızım",
            "/kayit/": "Kayıt ol · Kararsızım",
            poll.get_absolute_url(): "Çay mı kahve mi? · Kararsızım",
        }
        for url, title in expected.items():
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f"<title>{title}</title>", html=False)

        self.client.force_login(member)
        for url, title in {"/anket/yeni/": "Anket oluştur · Kararsızım", "/anketlerim/": "Anketlerim · Kararsızım"}.items():
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f"<title>{title}</title>", html=False)


class HeaderAndMessagesTests(TestCase):
    def test_guest_nav(self):
        html = self.client.get("/").content.decode()
        self.assertIn('aria-label="Anket oluştur"', html)
        self.assertIn('href="/giris/"', html)
        self.assertIn('href="/kayit/"', html)
        self.assertNotIn("data-menu", html)

    def test_login_link_carries_next_on_get_pages_only(self):
        poll = make_poll(make_user("sahip"))
        self.assertContains(self.client.get(poll.get_absolute_url()), f'href="/giris/?next=/anket/{poll.pk}/"')
        # the 403 page for a guest's POST must not suggest returning to a POST-only URL
        response = self.client.post(f"/anket/{poll.pk}/sil/")
        self.assertContains(response, 'href="/giris/"', status_code=403)

    def test_member_menu(self):
        self.client.force_login(make_user("ayse"))
        html = self.client.get("/").content.decode()
        self.assertIn("data-menu", html)
        self.assertIn("@ayse", html)
        self.assertIn('href="/anketlerim/"', html)
        self.assertIn('action="/cikis/"', html)
        self.assertIn("Çıkış yap", html)
        self.assertNotIn('href="/giris/"', html)

    def test_message_levels_and_roles(self):
        owner = make_user("sahip")
        self.client.force_login(owner)
        created = self.client.post("/anket/yeni/", {"question": "Soru?", "options": ["A", "B"]}, follow=True)
        self.assertContains(created, 'class="message message--success" role="status"')

        poll = make_poll(make_user("yazar"))
        failed = self.client.post(f"/anket/{poll.pk}/oy/", {"option_id": "x"}, follow=True)
        self.assertContains(failed, 'class="message message--error" role="alert"')
