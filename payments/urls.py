from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("start/<str:number>/", views.start, name="start"),
    path("callback/<int:payment_id>/", views.callback, name="callback"),
    path("result/<int:payment_id>/", views.result, name="result"),
    path("card/<str:number>/", views.card_to_card, name="card"),
    path("receipt/<int:payment_id>/", views.receipt, name="receipt"),
]
