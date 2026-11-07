from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("tinymce/", include("tinymce.urls")),
    path("health", core_views.health, name="health"),
    path("accounts/", include("accounts.urls")),
    path("cart/", include("cart.urls")),
    path("payments/", include("payments.urls")),
    path("blog/", include("blog.urls")),
    path("reviews/", include("reviews.urls")),
    path("", include("seo.urls")),
    path("", include("orders.urls")),
    path("", include("catalog.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
