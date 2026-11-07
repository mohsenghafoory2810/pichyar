from django.urls import path

from . import views

app_name = "seo"

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots"),
    path("llms.txt", views.llms_txt, name="llms"),
    path("sitemap.xml", views.sitemap_index, name="sitemap"),
    path("sitemap-<str:section>.xml", views.sitemap_section, name="sitemap_section"),
]
