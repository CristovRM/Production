def menu_permissions(request):
    if not request.user.is_authenticated:
        return {
            'can_access_thread': False,
            'can_access_thread_full': False,
            'can_access_weld': False,
            'can_access_weld_full': False,
            'can_access_phosphate': False,
            'can_access_cutting': False,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': False,
            'can_access_job_order': False,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': False,
            'can_access_connector': False,
            'can_access_graph': False,
            'can_access_dashboard': False,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
            'can_access_bevel': False,
        }
    
    user = request.user
    role = user.role
    operator_position = None
    leadman_position = None
    
    # Get position untuk operator
    if role == 'operator' and user.operator:
        operator_position = user.operator.position
    
    # Get position untuk leadman
    if role == 'leadman':
        leadman_position = user.position
    
    if role in ['admin', 'supervisor']:
        return {
            'can_access_thread': True,
            'can_access_thread_full': True,
            'can_access_weld': True,
            'can_access_weld_full': True,
            'can_access_phosphate': True,
            'can_access_cutting': True,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': True,
            'can_access_job_order': True,
            'can_access_joint_number': True,
            'can_access_protector': True,
            'can_access_maintenance': True,
            'can_access_connector': True,
            'can_access_graph': True,
            'can_access_dashboard': True,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
            'can_access_bevel': True,
        }
    
    elif role == 'leadman':
        return {
            'can_access_thread': (leadman_position == 'THREAD'),
            'can_access_thread_full': (leadman_position == 'THREAD'),
            'can_access_weld': (leadman_position == 'WELD'),
            'can_access_weld_full': (leadman_position == 'WELD'),
            'can_access_phosphate': True,
            'can_access_cutting': True,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': False,
            'can_access_job_order': True,
            'can_access_joint_number': True,
            'can_access_protector': True,
            'can_access_maintenance': True,
            'can_access_connector': True,
            'can_access_graph': True,
            'can_access_dashboard': True,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': True,
            'can_access_bevel': True,
        }
    
    elif role == 'management':
        return {
            'can_access_thread': False,
            'can_access_thread_full': False,
            'can_access_weld': False,
            'can_access_weld_full': False,
            'can_access_phosphate': False,
            'can_access_cutting': True,
            'can_access_thread_reports_only': True,
            'can_access_weld_reports_only': True,
            'can_access_master_data': False,
            'can_access_job_order': True,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': False,
            'can_access_connector': False,
            'can_access_graph': True,
            'can_access_dashboard': False,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
            'can_access_bevel': False,
        }
    
    elif role == 'maintenance':
        return {
            'can_access_thread': False,
            'can_access_thread_full': False,
            'can_access_weld': False,
            'can_access_weld_full': False,
            'can_access_phosphate': False,
            'can_access_cutting': False,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': False,
            'can_access_job_order': False,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': True,
            'can_access_connector': False,
            'can_access_graph': False,
            'can_access_dashboard': False,
            'is_operator_limited': False,
            'is_maintenance_only': True,
            'is_leadman_limited': False,
            'can_access_bevel': False,
        }
    
    elif role == 'engineer':
        return {
            'can_access_thread': True,
            'can_access_thread_full': True,
            'can_access_weld': True,
            'can_access_weld_full': True,
            'can_access_phosphate': True,
            'can_access_cutting': True,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': True,
            'can_access_job_order': True,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': True,
            'can_access_connector': False,
            'can_access_graph': True,
            'can_access_dashboard': True,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
            'can_access_bevel': True,
        }
    
    elif role == 'operator':
        return {
            'can_access_thread': (operator_position == 'THREAD'),
            'can_access_thread_full': False,
            'can_access_weld': (operator_position == 'WELD'),
            'can_access_weld_full': False,
            'can_access_phosphate': True,
            'can_access_cutting': True,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': False,
            'can_access_job_order': False,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': False,
            'can_access_connector': (operator_position == 'WELD'),
            'can_access_graph': False,
            'can_access_dashboard': False,
            'is_operator_limited': True,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
            'can_access_bevel': True,
        }
    
    else:
        return {
            'can_access_thread': False,
            'can_access_thread_full': False,
            'can_access_weld': False,
            'can_access_weld_full': False,
            'can_access_phosphate': False,
            'can_access_cutting': False,
            'can_access_thread_reports_only': False,
            'can_access_weld_reports_only': False,
            'can_access_master_data': False,
            'can_access_job_order': False,
            'can_access_joint_number': False,
            'can_access_protector': False,
            'can_access_maintenance': False,
            'can_access_connector': False,
            'can_access_graph': False,
            'can_access_dashboard': False,
            'is_operator_limited': False,
            'is_maintenance_only': False,
            'is_leadman_limited': False,
        }