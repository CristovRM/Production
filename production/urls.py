from django.urls import path
from . import views

urlpatterns = [
    path('ajax/get-machines/', views.get_machines_by_process, name='get_machines_by_process'),

    path('', views.index, name='production'),
    path('job/list', views.job_list, name='job_list'),
    path('job/add/', views.job_add, name='job_add'),
    path('report/oee', views.oee_dashboard, name='report_oee'),
    path('report/<int:header_id>/', views.daily_production_report, name='daily_report'),
    
    # Job Order
    path('joborder/add/', views.joborder_header, name='joborder_add'),
    path('joborder/list/', views.joborder_list, name='joborder_list'),
    path('joborder/get-filter-options/', views.get_filter_options, name='get_filter_options'),
    path('joborder/pdf/', views.joborder_pdf, name='joborder_pdf'),
    path('joborder/<int:header_id>/edit/', views.joborder_edit, name='joborder_edit'),
    path('joborder/<int:header_id>/detail/', views.joborder_detail, name='joborder_detail'),
    path('joborder/<int:header_id>/delete/', views.joborder_delete, name='joborder_delete'),
    path('joborder/<int:header_id>/detail/delete/', views.joborder_detail_delete, name='joborder_detail_delete'),
    path('joborder/tracking/<int:bjo_id>/', views.joborder_tracking, name='joborder_tracking'),
    path('joborder/print-report/<int:bjo_id>/', views.joborder_print_report, name='joborder_print_report'),
    path('joborder/tracking/hours/', views.tracking_hours, name='tracking_hours'),
    
    # Joint Number
    path('jointnumber/list/', views.jointnumber_list, name='jointnumber_list'),
    path('jointnumber/pdf/', views.jointnumber_pdf, name='jointnumber_pdf'),
    path('jointnumber/generate/', views.generate_joint_number, name='generate_joint_number'),
    path('jointnumber/manual-add/', views.manual_add_joint_number, name='manual_add_joint_number'),
    path('jointnumber/<int:pk>/edit/', views.edit_jointnumber, name='edit_jointnumber'),
    path('jointnumber/delete/<int:id>/', views.delete_jointnumber, name='delete_jointnumber'),
    
    # Box Protector
    path('boxprotector/list/', views.boxprotector_list, name='boxprotector_list'),
    path('boxprotector/pdf/', views.boxprotector_pdf, name='boxprotector_pdf'),
    path('boxprotector/<int:pk>/edit/', views.boxprotector_edit, name='boxprotector_edit'),
    path('boxprotector/generate/', views.generate_box_protector_view, name='generate_box_protector'),
    path('boxprotector/manual-add/', views.manual_add_box_protector, name='manual_add_box_protector'),
    path('boxprotector/delete/<int:id>/', views.delete_boxprotector, name='delete_boxprotector'),
    
    # Pin Protector
    path('pinprotector/list/', views.pinprotector_list, name='pinprotector_list'),
    path('pinprotector/pdf/', views.pinprotector_pdf, name='pinprotector_pdf'),
    path('pinprotector/generate/', views.pinprotector_generate, name='pinprotector_generate'),
    path('pinprotector/<int:pk>/edit/', views.pinprotector_edit, name='pinprotector_edit'),
    path('pinprotector/manual-add/', views.manual_add_pin_protector, name='manual_add_pin_protector'),
    path('pinprotector/delete/<int:id>/', views.delete_pinprotector, name='delete_pinprotector'),
    
    # Threading
    path('thread/list/', views.thread_list, name='thread_list'),
    path('thread/add/', views.thread_header, name='thread_add'),
    path('thread/edit/<int:header_id>/', views.thread_edit, name='thread_edit'),
    path('thread/delete/<int:header_id>/', views.thread_delete, name='thread_delete'),
    path('get-joint-numbers/', views.get_joint_numbers, name='get_joint_numbers'),
    path('ajax/get-ct-pb-values/', views.get_ct_pb_values, name='get_ct_pb_values'),
    path('get-bjo-connector-info/', views.get_bjo_connector_info, name='get_bjo_connector_info'),
    path('get-connector-number/', views.get_connector_number, name='get_connector_number'),
    path('thread/<int:header_id>/detail/', views.thread_detail, name='thread_detail'),
    path('thread/<int:header_id>/detail/delete/', views.thread_detail_delete, name='thread_detail_delete'),
    path('thread/report/<int:header_id>/', views.thread_report, name='thread_report'),
    path('thread/<int:pk>/final/', views.finalisasi_thread, name='finalisasi_thread'),
    path('thread/pdf/', views.thread_pdf, name='thread_pdf'),
    path('thread/excel/', views.thread_excel_export, name='thread_excel'),
    path('thread/report_oee/', views.thread_report_oee, name='thread_report_oee'),
    path('thread/report_oee_monthly/', views.thread_report_oee_monthly, name='thread_report_oee_monthly'),
    path('thread/report_oee_quarterly/', views.thread_report_oee_quarterly, name='thread_report_oee_quarterly'),
    path('thread/report_oee_yearly/', views.thread_report_oee_yearly, name='thread_report_oee_yearly'),
    # Booked Hours
    path('bookedhours/list/', views.bookedhours_list, name='bookedhours_list'),
    path('bookedhours/add/', views.bookedhours_add, name='bookedhours_add'),
    path('bookedhours/edit/<int:pk>/', views.bookedhours_edit, name='bookedhours_edit'),
    path('bookedhours/delete/<int:id>/', views.bookedhours_delete, name='bookedhours_delete'),
    
    # Connection
    path('connection/list/', views.connection_list, name='connection_list'),
    path('connection/add/', views.connection_add, name='connection_add'),
    path('connection/edit/<int:pk>/', views.connection_edit, name='connection_edit'),
    path('connection/delete/<int:id>/', views.connection_delete, name='connection_delete'),
    
    # Process
    path('process/list/', views.process_list, name='process_list'),
    path('process/add/', views.process_add, name='process_add'),
    path('process/edit/<int:pk>/', views.process_edit, name='process_edit'),
    path('process/delete/<int:id>/', views.process_delete, name='process_delete'),

    
    # Material Grade
    path('materialgrade/list/', views.materialgrade_list, name='materialgrade_list'),
    path('materialgrade/add/', views.materialgrade_add, name='materialgrade_add'),
    path('materialgrade/edit/<int:pk>/', views.materialgrade_edit, name='materialgrade_edit'),
    path('materialgrade/delete/<int:id>/', views.materialgrade_delete, name='materialgrade_delete'),
    
    # Machine
    path('machine/list/', views.machine_list, name='machine_list'),
    path('machine/add/', views.machine_add, name='machine_add'),
    path('machine/edit/<int:pk>/', views.machine_edit, name='machine_edit'),
    path('machine/delete/<int:id>/', views.machine_delete, name='machine_delete'),
    
    # Maintenance
    path('maintenance/list/', views.maintenance_list, name='maintenance_list'),
    path('maintenance/export-excel/', views.maintenance_export_excel, name='maintenance_export_excel'),
    path('maintenance/<int:pk>/edit/', views.maintenance_edit, name='maintenance_edit'),
    path('maintenance/delete/<int:id>/', views.maintenance_delete, name='maintenance_delete'),
    
    # OD Thickness
    path('odthickness/list/', views.odthickness_list, name='odthickness_list'),
    path('odthickness/add/', views.odthickness_add, name='odthickness_add'),
    path('odthickness/edit/<int:pk>/', views.odthickness_edit, name='odthickness_edit'),
    path('odthickness/delete/<int:id>/', views.odthickness_delete, name='odthickness_delete'),
    
    # Info Tag
    path('infotag/list/', views.infotag_list, name='infotag_list'),
    path('infotag/add/', views.infotag_add, name='infotag_add'),
    path('infotag/<int:pk>/edit/', views.infotag_edit, name='infotag_edit'),
    path('infotag/delete/<int:id>/', views.infotag_delete, name='infotag_delete'),
    
    # Cycle Time
    path('cycletime/list/', views.cycletime_list, name='cycletime_list'),
    path('cycletime/add/', views.cycletime_add, name='cycletime_add'),
    path('cycletime/<int:pk>/edit/', views.cycletime_edit, name='cycletime_edit'),
    path('cycletime/delete/<int:id>/', views.cycletime_delete, name='cycletime_delete'),
    path('cycletime/pdf/', views.cycletime_pdf, name='cycletime_pdf'),
    
    # Shift
    path('shift/list/', views.shift_list, name='shift_list'),
    path('shift/add/', views.shift_add, name='shift_add'),
    path('shift/edit/<int:pk>/', views.shift_edit, name='shift_edit'),
    path('shift/delete/<int:id>/', views.shift_delete, name='shift_delete'),
    
    # Operator
    path('operator/list/', views.operator_list, name='operator_list'),
    path('operator/add/', views.operator_add, name='operator_add'),
    path('operator/<int:pk>/edit/', views.operator_edit, name='operator_edit'),
    path('operator/delete/<int:id>/', views.operator_delete, name='operator_delete'),
    
    #Price Book
    path('pricebook/list', views.pricebook_list, name='pricebook_list'),
    path('pricebook/add', views.pricebook_add, name='pricebook_add'),
    path('pricebook/edit/<int:pk>', views.pricebook_edit, name='pricebook_edit'),
    path('pricebook/delete/<int:id>/', views.pricebook_delete, name='pricebook_delete'),
    path('pricebook/pdf/', views.pricebook_pdf, name='pricebook_pdf'),
    path('ajax/get-od-thickness/', views.get_od_thickness_by_process, name='get_od_thickness_by_process'),
    
    # Threading NCR
    path('thread/ncr/list/', views.thread_ncr_list, name='thread_ncr_list'),
    path('thread/ncr/create/', views.thread_ncr_create, name='thread_ncr_create'),
    path('thread/ncr/edit/<int:id>/', views.thread_ncr_edit, name='thread_ncr_edit'),
    path('thread/ncr/delete/<int:id>/', views.thread_ncr_delete, name='thread_ncr_delete'),
    
    # Threading Consumption
    path('thread/consumption/list/', views.thread_consumption_list, name='thread_consumption_list'),
    path('thread/consumption/edit/<int:pk>/', views.thread_consumption_edit, name='thread_consumption_edit'),
    path('thread/consumption/delete/<int:pk>/', views.thread_consumption_delete, name='thread_consumption_delete'),
    
    # Welding
    path('weld/list/', views.weld_list, name='weld_list'),
    path('weld/add/', views.weld_add, name='weld_add'),
    path('weld/edit/<int:header_id>/', views.weld_edit, name='weld_edit'),
    path('weld/delete/<int:id>/', views.weld_delete, name='weld_delete'),
    path('weld/<int:header_id>/detail/', views.weld_detail, name='weld_detail'),
    path('weld/<int:header_id>/detail/delete/', views.weld_detail_delete, name='weld_detail_delete'),
    path('ajax/get-connection-numbers/', views.get_connection_numbers, name='get_connection_numbers'),
    path('ajax/get-weld-ct-values/', views.get_weld_ct_values, name='get_weld_ct_values'),
    path('ajax/check-connector-duplicate/', views.check_connector_duplicate_ajax, name='check_connector_duplicate_ajax'),
    path('weld/<int:pk>/final/', views.finalisasi_weld, name='finalisasi_weld'),
    path('weld/<int:header_id>/report/', views.weld_report, name='weld_report'),
    path('weld/pdf/', views.weld_pdf, name='weld_pdf'),
    path('weld/excel/', views.weld_excel_export, name='weld_excel'),
    path('weld/report_oee/', views.weld_report_oee, name='weld_report_oee'),
    path('weld/check-conn-number/', views.check_conn_number_duplicate, name='check_conn_number_duplicate'),
    path('weld/report_oee_monthly/', views.weld_report_oee_monthly, name='weld_report_oee_monthly'),
    path('weld/report_oee_quarterly/', views.weld_report_oee_quarterly, name='weld_report_oee_quarterly'),
    path('weld/report_oee_yearly/', views.weld_report_oee_yearly, name='weld_report_oee_yearly'),
    
    # Welding NCR
    path('weld/ncr/list/', views.weld_ncr_list, name='weld_ncr_list'),
    path('weld/ncr/create/', views.weld_ncr_create, name='weld_ncr_create'),
    path('weld/ncr/edit/<int:id>/', views.weld_ncr_edit, name='weld_ncr_edit'),
    path('weld/ncr/delete/<int:id>/', views.weld_ncr_delete, name='weld_ncr_delete'),
    
    # Welding Consumption
    path('weld/consumption/list/', views.weld_consumption_list, name='weld_consumption_list'),
    path('weld/consumption/edit/<int:pk>/', views.weld_consumption_edit, name='weld_consumption_edit'),
    path('weld/consumption/delete/<int:pk>/', views.weld_consumption_delete, name='weld_consumption_delete'),
    
    # Connector 
    path('connector/get-joint-numbers/', views.get_joint_numbers_for_connector, name='get_joint_numbers_for_connector'),
    path('connector/', views.connector_list, name='connector_list'),
    path('connector/add/', views.connector_add, name='connector_add'),
    path('connector/<int:connector_id>/edit/', views.connector_edit, name='connector_edit'),
    path('connector/<int:connector_id>/delete/', views.connector_delete, name='connector_delete'),
    
    path('fix-data/', views.fix_data, name='fix_data'),
]