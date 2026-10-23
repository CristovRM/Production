from functools import wraps
from django.shortcuts import redirect
from django.http import HttpResponseForbidden


# ============================================
# BEVELING DECORATORS
# ============================================

def beveling_access_required(view_func):
    """
    Decorator untuk akses READ beveling module (list & detail).
    Allowed: Admin, Supervisor, Engineer, Leadman, Operator
    Untuk: bevel_list, bevel_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles - semua role ini bisa akses tanpa cek position
        allowed_roles = ['admin', 'supervisor', 'engineer', 'leadman', 'operator']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access beveling module."
        )
    
    return wrapper


def beveling_write_access_required(view_func):
    """
    Decorator untuk akses WRITE beveling module (create, edit basic).
    Allowed: Admin, Supervisor, Leadman, Operator
    Untuk: bevel_header, bevel_edit, bevel_delete, handle_update_consumable
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles - semua role ini bisa write tanpa cek position
        allowed_roles = ['admin', 'supervisor', 'leadman', 'operator']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify beveling data."
        )
    
    return wrapper


def beveling_detail_edit_access_required(view_func):
    """
    Decorator untuk akses EDIT DETAIL beveling (termasuk engineer).
    Allowed: Admin, Supervisor, Engineer, Leadman, Operator
    Untuk: handle_edit_bevel_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles - semua role ini bisa edit detail tanpa cek position
        allowed_roles = ['admin', 'supervisor', 'engineer', 'leadman', 'operator']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to edit beveling details."
        )
    
    return wrapper


def beveling_management_access_required(view_func):
    """
    Decorator untuk akses MANAGEMENT beveling (delete detail, edit time, finalize).
    Allowed: Admin, Supervisor, Leadman ONLY (NO OPERATOR)
    Untuk: bevel_detail_delete, handle_edit_time_bevel_detail, finalisasi_bevel
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk management functions
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # No operator access for management functions
        return HttpResponseForbidden(
            "Access Denied: Only Admin, Supervisor, or Leadman can perform this action."
        )
    
    return wrapper


def beveling_posted_edit_access_required(view_func):
    """
    Decorator untuk akses EDIT beveling yang sudah POSTED.
    Allowed: Admin, Supervisor ONLY
    Untuk: bevel_edit (ketika record sudah posted)
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Hanya Admin dan Supervisor yang bisa edit posted records
        if user.role in ['admin', 'supervisor']:
            return view_func(request, *args, **kwargs)
        
        # Untuk role lain, tolak akses
        return HttpResponseForbidden(
            "Access Denied: Only Admin and Supervisor can edit posted beveling records."
        )
    
    return wrapper


# ============================================
# BEVELING NCR & CONSUMPTION DECORATORS
# ============================================

def beveling_ncr_access_required(view_func):
    """
    Decorator untuk akses Beveling NCR module.
    Allowed: Admin, Supervisor, Engineer, Leadman ONLY (NO OPERATOR)
    Untuk: bevel_ncr_list, bevel_ncr_detail, bevel_ncr_create, bevel_ncr_edit, bevel_ncr_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk NCR module
        allowed_roles = ['admin', 'supervisor', 'engineer', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Beveling NCR module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Beveling NCR module."
        )
    
    return wrapper


def beveling_consumption_access_required(view_func):
    """
    Decorator untuk akses Beveling Consumption module.
    Allowed: Admin, Supervisor, Engineer, Leadman ONLY (NO OPERATOR)
    Untuk: bevel_consumption_list, bevel_consumption_detail, bevel_consumption_create, bevel_consumption_edit, bevel_consumption_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk Consumption module
        allowed_roles = ['admin', 'supervisor', 'engineer', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Beveling Consumption module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Beveling Consumption module."
        )
    
    return wrapper


def beveling_report_access_required(view_func):
    """
    Decorator untuk akses Beveling Reports.
    Allowed: Admin, Supervisor, Engineer, Management, Leadman (NO OPERATOR)
    Untuk: bevel_report_oee, bevel_report_oee_monthly, bevel_report_oee_quarterly, bevel_report_oee_yearly
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk Reports
        allowed_roles = ['admin', 'supervisor', 'engineer', 'management', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Beveling Reports."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Beveling Reports."
        )
    
    return wrapper