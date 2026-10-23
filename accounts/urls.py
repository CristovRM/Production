from django.urls import path
from .views import CustomLoginView
from . import views

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login_alt'),
    path('', views.index, name='accounts'),
    path('users/list/', views.user_list, name='user_list'),
    path('users/add/', views.user_add, name='user_add'),
    path('users/edit/<int:pk>/', views.user_edit, name='user_edit'),
]