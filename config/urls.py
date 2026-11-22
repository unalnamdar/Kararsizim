from django.contrib import admin
from django.urls import include, path

from .views import FaviconRedirectView

urlpatterns = [
    path("favicon.ico", FaviconRedirectView.as_view()),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("polls.urls")),
]
