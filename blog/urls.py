from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.article_list, name="list"),
    path("category/<str:slug>/", views.category_detail, name="category"),
    path("tag/<str:slug>/", views.tag_detail, name="tag"),
    path("<str:slug>/", views.article_detail, name="article"),
]
