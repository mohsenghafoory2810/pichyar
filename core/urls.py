from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("pages/<str:slug>/", views.static_page, name="page"),
    path("age-check/", views.age_confirm, name="age_confirm"),
]
