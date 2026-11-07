from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.order_list, name="orders"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("addresses/", views.address_list, name="addresses"),
    path("addresses/new/", views.address_form, name="address_add"),
    path("addresses/<int:pk>/", views.address_form, name="address_edit"),
    path("addresses/<int:pk>/delete/", views.address_delete, name="address_delete"),
    path("profile/", views.profile, name="profile"),
]
