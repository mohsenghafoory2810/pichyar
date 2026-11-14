from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("new/", views.ticket_new, name="new"),
    path("<int:pk>/", views.ticket_detail, name="detail"),
]
