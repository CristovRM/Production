from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='weldfinal'),
    path('header/', views.weldfinal_header_view, name='weldfinal_header'),
    path('detail/<int:header_id>/', views.weldfinal_detail_view, name='weldfinal_detail'),
    path('detail/delete/<int:detail_id>/', views.weldfinal_detail_delete, name='weldfinal_detail_delete'),
    path('update/<int:header_id>/<int:detail_id>/', views.weldfinal_update, name='weldfinal_update'),
    path('report/<int:header_id>/', views.weldfinal_report, name='weldfinal_report'),
    path('summary/', views.weldfinal_summary, name='weldfinal_summary'),
    path('summary/edit/<int:header_id>/', views.weldfinal_summary_edit, name='weldfinal_summary_edit'),
    path('summary/delete/<int:header_id>/', views.weldfinal_summary_delete, name='weldfinal_summary_delete'),
    path('summary/detail/<int:header_id>/', views.weldfinal_summary_detail, name='weldfinal_summary_detail'),
    path('tracking/', views.weldfinal_joint_tracking, name='weldfinal_joint_tracking'),
]