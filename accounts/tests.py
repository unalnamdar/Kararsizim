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
