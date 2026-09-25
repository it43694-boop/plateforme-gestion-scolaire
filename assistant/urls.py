from django.urls import path

from assistant import views

app_name = "assistant"

urlpatterns = [
    path("", views.poser_question, name="poser_question"),
]
