from django.urls import path
from . import views

urlpatterns = [
    path('summary/', views.cutting_summary, name='cutting_summary'),
    path('header/', views.cutting_header, name='cutting_header'),
    path('detail/<int:header_id>/', views.cutting_detail, name='cutting_detail'),
    path('edit/<int:header_id>/', views.cutting_edit, name='cutting_edit'),
    path('delete/<int:header_id>/', views.cutting_delete, name='cutting_delete'),
    path('report/<int:header_id>/', views.cutting_report, name='cutting_report'),
    path('', views.index, name='cutting'),
    ]