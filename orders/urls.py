from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/mobile/", views.checkout_mobile, name="checkout_mobile"),
    path("checkout/address/<int:pk>/", views.address_fields, name="checkout_address"),
    path("checkout/discount/", views.discount, name="discount"),
    path("orders/track/", views.track, name="track"),
    path("orders/<str:number>/", views.detail, name="detail"),
]
