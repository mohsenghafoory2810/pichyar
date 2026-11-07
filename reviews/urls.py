from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("product/<int:product_id>/", views.review_list, name="list"),
    path("product/<int:product_id>/submit/", views.submit_review, name="submit"),
]
