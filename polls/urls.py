from django.urls import path

from . import views

app_name = "polls"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("anket/yeni/", views.create, name="create"),
    path("anket/<int:poll_id>/", views.detail, name="detail"),
    path("anket/<int:poll_id>/oy/", views.vote, name="vote"),
    path("anket/<int:poll_id>/bildir/", views.report, name="report"),
    path("anket/<int:poll_id>/sil/", views.delete, name="delete"),
    path("anketlerim/", views.my_polls, name="my_polls"),
]
