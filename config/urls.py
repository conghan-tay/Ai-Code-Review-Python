from django.urls import include, path

urlpatterns = [
    path("api/", include("inventory.urls")),
]
