from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="api-login"),
    path("logout/", views.logout_view, name="api-logout"),
    path("me/", views.me_view, name="api-me"),
    path("users/", views.users_collection, name="api-users"),
    path("users/<int:user_id>/", views.users_detail, name="api-user-detail"),
]

