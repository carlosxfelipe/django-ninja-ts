from django.urls import path

from tests.sample_api import api

urlpatterns = [path("api/", api.urls)]
