from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_normalizes_username_and_email(self):
        user = User.objects.create_user(email="Ali@Example.COM", username="Ali_42", password="g8#kLq!29zPa")
        self.assertEqual(user.username, "ali_42")
        self.assertEqual(user.email, "ali@example.com")
        self.assertTrue(user.check_password("g8#kLq!29zPa"))
        self.assertFalse(user.is_staff)

    def test_login_uses_email(self):
        User.objects.create_user(email="ali@example.com", username="ali", password="g8#kLq!29zPa")
        self.assertIsNotNone(authenticate(email="ALI@example.com", password="g8#kLq!29zPa"))
        self.assertIsNone(authenticate(email="ali@example.com", password="wrong"))

    def test_username_is_case_insensitive_unique(self):
        User.objects.create_user(email="a@example.com", username="ali", password="x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(email="b@example.com", username="ALI", password="x")

    def test_email_is_case_insensitive_unique(self):
        User.objects.create_user(email="a@example.com", username="ali", password="x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(email="A@EXAMPLE.com", username="veli", password="x")

    def test_username_validation(self):
        for bad in ["ab", "a" * 21, "ali-veli", "ali veli", "çağrı"]:
            with self.subTest(username=bad):
                user = User(email="x@example.com", username=bad)
                user.set_password("g8#kLq!29zPa")
                with self.assertRaises(ValidationError):
                    user.full_clean()

    def test_create_superuser(self):
        admin = User.objects.create_superuser(email="admin@example.com", username="admin", password="x")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class HomePageTests(TestCase):
    def test_home_shows_title(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kararsızım")


STRONG_PASSWORD = "g8#kLq!29zPa"


def signup_data(**overrides):
    data = {
        "email": "ayse@example.com",
        "username": "ayse",
        "password1": STRONG_PASSWORD,
        "password2": STRONG_PASSWORD,
    }
    data.update(overrides)
    return data


class SignUpViewTests(TestCase):
    url = "/kayit/"

    def test_page_renders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kayıt ol")

    def test_successful_signup_logs_in_and_redirects_home(self):
        response = self.client.post(self.url, signup_data(email="Ayse@Example.com", username="Ayse_1"))
        self.assertRedirects(response, "/")
        user = User.objects.get()
        self.assertEqual(user.username, "ayse_1")
        self.assertEqual(user.email, "ayse@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

        home = self.client.get("/")
        self.assertContains(home, "@ayse_1")
        self.assertNotContains(home, "ayse@example.com")

    def test_signup_respects_safe_next(self):
        response = self.client.post(self.url + "?next=/anket/yeni/", signup_data())
        self.assertRedirects(response, "/anket/yeni/", fetch_redirect_response=False)

    def test_signup_ignores_external_next(self):
        response = self.client.post(self.url, signup_data(next="https://evil.example.com/"))
        self.assertRedirects(response, "/")

    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user(email="ayse@example.com", username="baska", password=STRONG_PASSWORD)
        response = self.client.post(self.url, signup_data(email="AYSE@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "email", "Bu e-posta adresiyle zaten bir hesap var.")
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_username_rejected_case_insensitively(self):
        User.objects.create_user(email="baska@example.com", username="ayse", password=STRONG_PASSWORD)
        response = self.client.post(self.url, signup_data(username="AySe"))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "username", "Bu kullanıcı adı alınmış.")
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_usernames_rejected(self):
        cases = {
            "ab": "Kullanıcı adı 3–20 karakter olmalı.",
            "a" * 21: "Kullanıcı adı 3–20 karakter olmalı.",
            "ayşe": "Kullanıcı adı yalnızca harf (a-z), rakam ve alt çizgi (_) içerebilir.",
            "ali-veli": "Kullanıcı adı yalnızca harf (a-z), rakam ve alt çizgi (_) içerebilir.",
            "ali veli": "Kullanıcı adı yalnızca harf (a-z), rakam ve alt çizgi (_) içerebilir.",
        }
        for username, message in cases.items():
            with self.subTest(username=username):
                response = self.client.post(self.url, signup_data(username=username))
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.context["form"].errors["username"])
        self.assertFalse(User.objects.exists())

    def test_password_mismatch_rejected(self):
        response = self.client.post(self.url, signup_data(password2="baska#Parola91"))
        self.assertFormError(response.context["form"], "password2", "Parolalar birbiriyle eşleşmiyor.")
        self.assertFalse(User.objects.exists())

    def test_password_validators_enabled(self):
        # too short, all numeric, too common, too similar to the email
        for weak in ["kisa1", "12345678901", "password123", "ayse@example.com"]:
            with self.subTest(password=weak):
                response = self.client.post(self.url, signup_data(password1=weak, password2=weak))
                self.assertEqual(response.status_code, 200)
                self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_authenticated_user_is_redirected(self):
        user = User.objects.create_user(email="a@example.com", username="ali", password=STRONG_PASSWORD)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), "/")


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ayse@example.com", username="ayse", password=STRONG_PASSWORD)

    def test_login_with_email_and_password(self):
        response = self.client.post("/giris/", {"username": "AYSE@example.com", "password": STRONG_PASSWORD})
        self.assertRedirects(response, "/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_wrong_password(self):
        response = self.client.post("/giris/", {"username": "ayse@example.com", "password": "yanlis"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "E-posta veya parola hatalı.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_redirects_to_next(self):
        response = self.client.post(
            "/giris/?next=/anket/yeni/",
            {"username": "ayse@example.com", "password": STRONG_PASSWORD, "next": "/anket/yeni/"},
        )
        self.assertRedirects(response, "/anket/yeni/", fetch_redirect_response=False)

    def test_login_ignores_external_next(self):
        response = self.client.post(
            "/giris/", {"username": "ayse@example.com", "password": STRONG_PASSWORD, "next": "https://evil.example.com/"}
        )
        self.assertRedirects(response, "/")

    def test_login_page_keeps_next_in_form(self):
        response = self.client.get("/giris/?next=/anket/yeni/")
        self.assertContains(response, 'name="next" value="/anket/yeni/"')

    def test_authenticated_user_redirected_from_login(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get("/giris/"), "/")

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/cikis/").status_code, 405)
        response = self.client.post("/cikis/")
        self.assertRedirects(response, "/")
        self.assertNotIn("_auth_user_id", self.client.session)


class HeaderTests(TestCase):
    def test_guest_sees_login_and_signup(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="/giris/"')
        self.assertContains(response, 'href="/kayit/"')
        self.assertNotContains(response, "Çıkış")

    def test_member_sees_username_and_logout(self):
        user = User.objects.create_user(email="ayse@example.com", username="ayse", password=STRONG_PASSWORD)
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertContains(response, "@ayse")
        self.assertContains(response, 'action="/cikis/"')
        self.assertNotContains(response, 'href="/kayit/"')
        self.assertNotContains(response, "ayse@example.com")
