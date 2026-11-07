from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("c/<str:slug>/", views.category_detail, name="category"),
    path("p/<str:slug>/", views.product_detail, name="product"),
]
