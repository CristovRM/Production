from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='bevel'),
    path('list/', views.bevel_list, name='bevel_list'),
    path('add/', views.bevel_header, name='bevel_add'),
    path('edit/<int:header_id>/', views.bevel_edit, name='bevel_edit'),
    path('delete/<int:header_id>/', views.bevel_delete, name='bevel_delete'),
    path('detail/<int:header_id>/', views.bevel_detail, name='bevel_detail'),
    path('detail/<int:header_id>/delete/', views.bevel_detail_delete, name='bevel_detail_delete'),
    path('ajax/get-joint-numbers/', views.get_bevel_joint_numbers, name='bevel_get_joint_numbers'),
    path('ajax/get-ct-pb-values/', views.get_bevel_ct_pb_values, name='bevel_get_ct_pb_values'),
    path('ajax/get-connector-info/', views.get_bevel_connector_info, name='bevel_get_connector_info'),
    path('ajax/get-connector-number/', views.get_bevel_connector_number, name='bevel_get_connector_number'),
    path('report/<int:header_id>/', views.bevel_report, name='bevel_report'),
    path('finalisasi/<int:pk>/', views.finalisasi_bevel, name='finalisasi_bevel'),
    path('consumption/', views.bevel_consumption_list, name='bevel_consumption_list'),
    path('consumption/edit/<int:pk>/', views.bevel_consumption_edit, name='bevel_consumption_edit'),
    path('consumption/delete/<int:pk>/', views.bevel_consumption_delete, name='bevel_consumption_delete'),
    path('ncr/', views.bevel_ncr_list, name='bevel_ncr_list'),
    path('ncr/create/', views.bevel_ncr_create, name='bevel_ncr_create'),
    path('ncr/edit/<int:id>/', views.bevel_ncr_edit, name='bevel_ncr_edit'),
    path('ncr/delete/<int:id>/', views.bevel_ncr_delete, name='bevel_ncr_delete'),
    path('report/oee/', views.bevel_report_oee, name='bevel_report_oee'),
    path('report/oee/monthly/', views.bevel_report_oee_monthly, name='bevel_report_oee_monthly'),
    path('report/oee/quarterly/', views.bevel_report_oee_quarterly, name='bevel_report_oee_quarterly'),
    path('report/oee/yearly/', views.bevel_report_oee_yearly, name='bevel_report_oee_yearly'),
]