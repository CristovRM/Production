from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='oee'),
    path('oee/threading/', views.oee_threading, name='oee_threading'),
    path('oee/welding/', views.oee_welding, name='oee_welding'),
]
