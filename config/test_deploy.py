"""Phase 5 checks: the files Vercel relies on, and the production settings.

Settings are computed when the module is imported, so the production cases run in a subprocess
with their own environment (an env var always wins over `.env`, so these runs never touch the
developer's real database).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.utils import get_random_secret_key
from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent

SETTINGS_PROBE = """
import json, os
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
from django.conf import settings as s
db = s.DATABASES["default"]
print(json.dumps({
    "debug": s.DEBUG,
    "session_cookie_secure": s.SESSION_COOKIE_SECURE,
    "csrf_cookie_secure": s.CSRF_COOKIE_SECURE,
    "ssl_redirect": s.SECURE_SSL_REDIRECT,
    "proxy_header": list(s.SECURE_PROXY_SSL_HEADER),
    "hsts": s.SECURE_HSTS_SECONDS,
    "allowed_hosts": s.ALLOWED_HOSTS,
    "csrf_origins": s.CSRF_TRUSTED_ORIGINS,
    "engine": db["ENGINE"],
    "conn_max_age": db["CONN_MAX_AGE"],
    "options": db.get("OPTIONS", {}),
    "server_side_cursors_disabled": db.get("DISABLE_SERVER_SIDE_CURSORS"),
}))
"""


def run_python(*args, **env):
    # A throwaway random key: a repetitive one such as "x" * 60 would trigger check --deploy's W009.
    full_env = {**os.environ, "DEBUG": "False", "SECRET_KEY": get_random_secret_key(), "DATABASE_URL": "", **env}
    return subprocess.run(
        [sys.executable, *args], cwd=BASE_DIR, env=full_env, capture_output=True, text=True, timeout=120
    )


def production_settings(**env):
    result = run_python("-c", SETTINGS_PROBE, **env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


class VercelFilesTests(SimpleTestCase):
    def test_django_is_detectable(self):
        """Vercel finds Django through manage.py at the repo root and settings.WSGI_APPLICATION."""
        self.assertTrue((BASE_DIR / "manage.py").exists())
        self.assertEqual(settings.WSGI_APPLICATION, "config.wsgi.application")
        from config.wsgi import application

        self.assertTrue(callable(application))

    def test_python_version_file(self):
        self.assertEqual((BASE_DIR / ".python-version").read_text().strip(), "3.12")

    def test_vercel_json_pins_the_function_to_the_database_region(self):
        config = json.loads((BASE_DIR / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(config["regions"], ["fra1"])  # Supabase runs in eu-central-1 (Frankfurt)
        self.assertNotIn("builds", config)  # the legacy builds/routes style is not used

    def test_static_files_can_be_collected(self):
        """Vercel runs collectstatic itself when STATIC_ROOT is set."""
        self.assertTrue(settings.STATIC_ROOT)
        call_command("collectstatic", interactive=False, dry_run=True, verbosity=0)

    def test_requirements_cover_production(self):
        text = (BASE_DIR / "requirements.txt").read_text().lower()
        for package in ("django==", "psycopg[binary]==", "dj-database-url==", "python-dotenv=="):
            self.assertIn(package, text)

    def test_example_env_has_no_secrets(self):
        lines = (BASE_DIR / ".env.example").read_text().splitlines()
        for name in ("SECRET_KEY", "DATABASE_URL"):
            line = next(line for line in lines if line.startswith(f"{name}="))
            self.assertEqual(line, f"{name}=", f"{name} must be empty in .env.example")
        ignored = (BASE_DIR / ".gitignore").read_text().splitlines()
        self.assertIn(".env", ignored)
        self.assertIn("!.env.example", ignored)

    def test_request_errors_are_logged_to_the_console(self):
        """Without this, tracebacks of failed requests would not appear in Vercel's function logs."""
        logger = settings.LOGGING["loggers"]["django.request"]
        self.assertIn("console", logger["handlers"])
        self.assertEqual(logger["level"], "ERROR")


class ProductionSettingsTests(SimpleTestCase):
    def test_security_flags_with_debug_off(self):
        s = production_settings()
        self.assertFalse(s["debug"])
        self.assertTrue(s["session_cookie_secure"])
        self.assertTrue(s["csrf_cookie_secure"])
        self.assertTrue(s["ssl_redirect"])
        self.assertEqual(s["proxy_header"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertGreater(s["hsts"], 0)
        self.assertIn(".vercel.app", s["allowed_hosts"])
        self.assertIn("https://*.vercel.app", s["csrf_origins"])

    def test_debug_defaults_to_off(self):
        """If DEBUG is not set on Vercel the site must not run in debug mode."""
        from config.settings import env_bool

        self.assertIs(env_bool("KARARSIZIM_SURELY_UNSET_VARIABLE", default=False), False)
        with mock.patch.dict(os.environ, {"KARARSIZIM_FLAG": "True"}):
            self.assertIs(env_bool("KARARSIZIM_FLAG"), True)
        with mock.patch.dict(os.environ, {"KARARSIZIM_FLAG": "false"}):
            self.assertIs(env_bool("KARARSIZIM_FLAG", default=True), False)
        source = (BASE_DIR / "config/settings.py").read_text(encoding="utf-8")
        self.assertIn('DEBUG = env_bool("DEBUG", default=False)', source)

    def test_missing_secret_key_stops_the_app(self):
        result = run_python("manage.py", "check", SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_check_deploy_only_reports_the_known_hsts_preload_warning(self):
        result = run_python("manage.py", "check", "--deploy")
        self.assertEqual(result.returncode, 0, result.stderr)
        warnings = set(re.findall(r"security\.W\d+", result.stdout + result.stderr))
        self.assertEqual(warnings, {"security.W021"})  # HSTS preload: not suitable for *.vercel.app

    def test_supabase_transaction_pooler_settings(self):
        """Port 6543 is pgbouncer in transaction mode: no prepared statements, no server-side cursors."""
        s = production_settings(DATABASE_URL="postgresql://user:pw@db.example.com:6543/postgres")
        self.assertTrue(s["engine"].endswith("postgresql"))
        self.assertEqual(s["conn_max_age"], 0)
        self.assertIsNone(s["options"]["prepare_threshold"])
        self.assertEqual(s["options"]["sslmode"], "require")
        self.assertTrue(s["server_side_cursors_disabled"])

    def test_sqlite_fallback_without_database_url(self):
        s = production_settings()
        self.assertTrue(s["engine"].endswith("sqlite3"))
