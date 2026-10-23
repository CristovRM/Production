from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='display'),
    path('info2', views.info2, name='info2'),
    path('produksi/tambah/', views.produksi_create, name='produksi_tambah'),
    path('grafikdata/list/', views.grafikdata_list, name='grafikdata_list'),
    path('grafikdata/add/', views.grafikdata_add, name='grafikdata_add'),
    path('grafikdata/edit/<int:pk>/', views.grafikdata_edit, name='grafikdata_edit'),
    path('grafikdata/delete/<int:id>/', views.grafikdata_delete, name='grafikdata_delete'),
    path('oeedashboard/', views.oee_dashboard, name='oee_dashboard'),
    path('oeedashboard/data/', views.oee_dashboard_data, name='oee_dashboard_data'),
]
