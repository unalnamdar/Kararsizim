from django.contrib.staticfiles.storage import staticfiles_storage
from django.shortcuts import render
from django.views.generic import RedirectView


def csrf_failure(request, reason=""):
    """Friendly Turkish 403 page for failed CSRF checks (stale tab, expired cookie)."""
    return render(request, "403.html", {"csrf_failure": True}, status=403)


class FaviconRedirectView(RedirectView):
    """Browsers and crawlers still ask for /favicon.ico; point them at the SVG icon."""

    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        return staticfiles_storage.url("img/favicon.svg")
