from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


# ============================================
# THREADING DECORATORS
# ============================================

def threading_access_required(view_func):
    """
    Decorator untuk akses READ threading module (list & detail).
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (THREAD), Operator (THREAD)
    Untuk: thread_list, thread_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can access this module."
                )
        
        # Special check untuk operator - harus position THREAD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD operators can access this module."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access threading module."
        )
    
    return wrapper


def threading_write_access_required(view_func):
    """
    Decorator untuk akses WRITE threading module (create, edit basic).
    Allowed: Admin, Supervisor
    Allowed with position check: Leadman (THREAD), Operator (THREAD)
    Untuk: thread_header, thread_edit, thread_delete, handle_update_consumable
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can perform this action."
                )
        
        # Special check untuk operator - harus position THREAD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD operators can perform this action."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify threading data."
        )
    
    return wrapper


def threading_detail_edit_access_required(view_func):
    """
    Decorator untuk akses EDIT DETAIL threading (termasuk engineer).
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (THREAD), Operator (THREAD)
    Untuk: handle_edit_thread_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can edit threading details."
                )
        
        # Special check untuk operator - harus position THREAD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD operators can edit threading details."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to edit threading details."
        )
    
    return wrapper


def threading_management_access_required(view_func):
    """
    Decorator untuk akses MANAGEMENT threading (delete detail, edit time, finalize).
    Allowed: Admin, Supervisor
    Allowed with position check: Leadman (THREAD) ONLY
    Untuk: thread_detail_delete, handle_edit_time_thread_detail, finalisasi_thread
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can perform this action."
                )
        
        # No operator access for management functions
        return HttpResponseForbidden(
            "Access Denied: Only Admin, Supervisor, or THREAD Leadman can perform this action."
        )
    
    return wrapper

def threading_posted_edit_access_required(view_func):
    """
    Decorator untuk akses EDIT threading yang sudah POSTED.
    Allowed: Admin, Supervisor ONLY
    Untuk: thread_edit (ketika record sudah posted)
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
            "Access Denied: Only Admin and Supervisor can edit posted threading records."
        )
    
    return wrapper


# ============================================
# NEW: THREADING NCR & CONSUMPTION DECORATORS
# ============================================

def threading_ncr_access_required(view_func):
    """
    Decorator untuk akses Threading NCR module.
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (THREAD) ONLY (NO OPERATOR)
    Untuk: thread_ncr_list, thread_ncr_detail, thread_ncr_create, thread_ncr_edit, thread_ncr_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can access Threading NCR module."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Threading NCR module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Threading NCR module."
        )
    
    return wrapper


def threading_consumption_access_required(view_func):
    """
    Decorator untuk akses Threading Consumption module.
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (THREAD) ONLY (NO OPERATOR)
    Untuk: thread_consumption_list, thread_consumption_detail, thread_consumption_create, thread_consumption_edit, thread_consumption_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can access Threading Consumption module."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Threading Consumption module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Threading Consumption module."
        )
    
    return wrapper


def threading_report_access_required(view_func):
    """
    Decorator untuk akses Threading Reports.
    Allowed: Admin, Supervisor, Engineer, Management
    Allowed with position check: Leadman (THREAD) (NO OPERATOR)
    Untuk: thread_report_oee, thread_report_oee_monthly, thread_report_oee_quarterly, thread_report_oee_yearly
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer', 'management']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position THREAD
        if user.role == 'leadman':
            if user.position == 'THREAD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only THREAD leadman can access Threading Reports."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Threading Reports."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Threading Reports."
        )
    
    return wrapper


# ============================================
# WELDING DECORATORS
# ============================================

def welding_access_required(view_func):
    """
    Decorator untuk akses READ welding module (list & detail).
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (WELD), Operator (WELD)
    Untuk: weld_list, weld_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can access this module."
                )
        
        # Special check untuk operator - harus position WELD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD operators can access this module."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access welding module."
        )
    
    return wrapper


def welding_write_access_required(view_func):
    """
    Decorator untuk akses WRITE welding module (create, edit basic).
    Allowed: Admin, Supervisor
    Allowed with position check: Leadman (WELD), Operator (WELD)
    Untuk: weld_add, weld_edit, weld_delete, handle_update_weld_consumable
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can perform this action."
                )
        
        # Special check untuk operator - harus position WELD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD operators can perform this action."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify welding data."
        )
    
    return wrapper


def welding_detail_edit_access_required(view_func):
    """
    Decorator untuk akses EDIT DETAIL welding (termasuk engineer).
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (WELD), Operator (WELD)
    Untuk: handle_edit_weld_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can edit welding details."
                )
        
        # Special check untuk operator - harus position WELD
        if user.role == 'operator':
            if user.operator and user.operator.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD operators can edit welding details."
                )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to edit welding details."
        )
    
    return wrapper


def welding_management_access_required(view_func):
    """
    Decorator untuk akses MANAGEMENT welding (delete detail, edit time, finalize).
    Allowed: Admin, Supervisor
    Allowed with position check: Leadman (WELD) ONLY
    Untuk: weld_detail_delete, handle_edit_time_weld_detail, finalisasi_weld
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can perform this action."
                )
        
        # No operator access for management functions
        return HttpResponseForbidden(
            "Access Denied: Only Admin, Supervisor, or WELD Leadman can perform this action."
        )
    
    return wrapper


# ============================================
# NEW: WELDING NCR & CONSUMPTION DECORATORS
# ============================================

def welding_ncr_access_required(view_func):
    """
    Decorator untuk akses Welding NCR module.
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (WELD) ONLY (NO OPERATOR)
    Untuk: weld_ncr_list, weld_ncr_detail, weld_ncr_create, weld_ncr_edit, weld_ncr_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can access Welding NCR module."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Welding NCR module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Welding NCR module."
        )
    
    return wrapper


def welding_consumption_access_required(view_func):
    """
    Decorator untuk akses Welding Consumption module.
    Allowed: Admin, Supervisor, Engineer
    Allowed with position check: Leadman (WELD) ONLY (NO OPERATOR)
    Untuk: weld_consumption_list, weld_consumption_detail, weld_consumption_create, weld_consumption_edit, weld_consumption_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can access Welding Consumption module."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Welding Consumption module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Welding Consumption module."
        )
    
    return wrapper


def welding_report_access_required(view_func):
    """
    Decorator untuk akses Welding Reports.
    Allowed: Admin, Supervisor, Engineer, Management
    Allowed with position check: Leadman (WELD) (NO OPERATOR)
    Untuk: weld_report_oee, weld_report_oee_monthly, weld_report_oee_quarterly, weld_report_oee_yearly
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles tanpa batasan position
        allowed_roles = ['admin', 'supervisor', 'engineer', 'management']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Special check untuk leadman - harus position WELD
        if user.role == 'leadman':
            if user.position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELD leadman can access Welding Reports."
                )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Welding Reports."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Welding Reports."
        )
    
    return wrapper

# ============================================
# JOB ORDER DECORATORS
# ============================================

def joborder_access_required(view_func):
    """
    Decorator untuk akses READ Job Order module (list & detail).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: joborder_list, joborder_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk read access
        allowed_roles = ['admin', 'supervisor', 'leadman','engineer']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Job Order module."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Job Order module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Job Order module."
        )
    
    return wrapper


def joborder_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Job Order module (create, edit).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: joborder_header, joborder_edit, handle_edit_joborder_detail
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk write access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Job Order data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot modify Job Order data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Job Order data."
        )
    
    return wrapper


def joborder_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Job Order (header & detail).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: joborder_delete, joborder_detail_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk delete access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Job Order data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Job Order data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Job Order data."
        )
    
    return wrapper


def joborder_pdf_access_required(view_func):
    """
    Decorator untuk akses PDF/Export Job Order.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: joborder_pdf
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk PDF access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot export Job Order data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot export Job Order data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to export Job Order data."
        )
    
    return wrapper

# ============================================
# JOINT NUMBER DECORATORS
# ============================================

def jointnumber_access_required(view_func):
    """
    Decorator untuk akses READ Joint Number module (list & detail).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: jointnumber_list
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk read access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Joint Number module."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Joint Number module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Joint Number module."
        )
    
    return wrapper


def jointnumber_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Joint Number module (generate, manual add).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: generate_joint_number, manual_add_joint_number
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk write access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Joint Number data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot modify Joint Number data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Joint Number data."
        )
    
    return wrapper


def jointnumber_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Joint Number.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: delete_jointnumber
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk delete access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Joint Number data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Joint Number data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Joint Number data."
        )
    
    return wrapper


def jointnumber_pdf_access_required(view_func):
    """
    Decorator untuk akses PDF/Export Joint Number.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: jointnumber_pdf
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk PDF access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot export Joint Number data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot export Joint Number data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to export Joint Number data."
        )
    
    return wrapper

# ============================================
# BOX PROTECTOR DECORATORS
# ============================================

def boxprotector_access_required(view_func):
    """
    Decorator untuk akses READ Box Protector module (list).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: boxprotector_list
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk read access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Box Protector module."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Box Protector module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Box Protector module."
        )
    
    return wrapper


def boxprotector_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Box Protector module (generate, manual add, edit).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: generate_box_protector_view, manual_add_box_protector, boxprotector_edit
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk write access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Box Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot modify Box Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Box Protector data."
        )
    
    return wrapper


def boxprotector_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Box Protector.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: delete_boxprotector
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk delete access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Box Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Box Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Box Protector data."
        )
    
    return wrapper


def boxprotector_pdf_access_required(view_func):
    """
    Decorator untuk akses PDF/Export Box Protector.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: boxprotector_pdf
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk PDF access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot export Box Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot export Box Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to export Box Protector data."
        )
    
    return wrapper

# ============================================
# PIN PROTECTOR DECORATORS
# ============================================

def pinprotector_access_required(view_func):
    """
    Decorator untuk akses READ Pin Protector module (list).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: pinprotector_list
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk read access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Pin Protector module."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Pin Protector module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Pin Protector module."
        )
    
    return wrapper


def pinprotector_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Pin Protector module (generate, manual add, edit).
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: pinprotector_generate, manual_add_pin_protector, pinprotector_edit
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk write access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Pin Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot modify Pin Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Pin Protector data."
        )
    
    return wrapper


def pinprotector_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Pin Protector.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: delete_pinprotector
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk delete access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Pin Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Pin Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Pin Protector data."
        )
    
    return wrapper


def pinprotector_pdf_access_required(view_func):
    """
    Decorator untuk akses PDF/Export Pin Protector.
    Allowed: Admin, Supervisor, Leadman ONLY
    Untuk: pinprotector_pdf
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk PDF access
        allowed_roles = ['admin', 'supervisor', 'leadman']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot export Pin Protector data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot export Pin Protector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to export Pin Protector data."
        )
    
    return wrapper

# ============================================
# MAINTENANCE DECORATORS
# ============================================

def maintenance_access_required(view_func):
    """
    Decorator untuk akses READ Maintenance module (list).
    Allowed: Admin, Supervisor, Leadman, Maintenance ONLY
    Untuk: maintenance_list
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk read access - INCLUDING MAINTENANCE
        allowed_roles = ['admin', 'supervisor', 'leadman', 'maintenance']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Maintenance module."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access Maintenance module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Maintenance module."
        )
    
    return wrapper


def maintenance_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Maintenance module (edit).
    Allowed: Admin, Supervisor, Leadman, Maintenance ONLY
    Untuk: maintenance_edit
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk write access - INCLUDING MAINTENANCE
        allowed_roles = ['admin', 'supervisor', 'leadman', 'maintenance']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Maintenance data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot modify Maintenance data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Maintenance data."
        )
    
    return wrapper


def maintenance_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Maintenance.
    Allowed: Admin, Supervisor, Leadman, Maintenance ONLY
    Untuk: maintenance_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Allowed roles untuk delete access - INCLUDING MAINTENANCE
        allowed_roles = ['admin', 'supervisor', 'leadman', 'maintenance']
        
        # Check role-based access
        if user.role in allowed_roles:
            return view_func(request, *args, **kwargs)
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Maintenance data."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Maintenance data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Maintenance data."
        )
    
    return wrapper

# ============================================
# CONNECTOR DECORATORS
# ============================================

def connector_access_required(view_func):
    """
    Decorator untuk akses READ Connector module (list).
    Allowed: Admin, Supervisor, Leadman, Operator WELD ONLY
    Blocked: Engineer, Maintenance, Operator THREAD
    Untuk: connector_list
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Admin, Supervisor, Leadman - full access
        if user.role in ['admin', 'supervisor', 'leadman']:
            return view_func(request, *args, **kwargs)
        
        # Operator - check position (hanya WELD yang bisa akses)
        if user.role == 'operator':
            # Cek posisi dari operator model atau user.position
            user_position = user.user_position  # Menggunakan property dari User model
            
            if user_position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELDING operators can access Connector module. "
                    "THREADING operators cannot access this module."
                )
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access Connector module."
            )
        
        # Block maintenance
        if user.role == 'maintenance':
            return HttpResponseForbidden(
                "Access Denied: Maintenance staff cannot access Connector module."
            )
        
        # Block management (jika ada)
        if user.role == 'management':
            return HttpResponseForbidden(
                "Access Denied: Management cannot access Connector module."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access Connector module."
        )
    
    return wrapper


def connector_write_access_required(view_func):
    """
    Decorator untuk akses WRITE Connector module (add, edit).
    Allowed: Admin, Supervisor, Leadman, Operator WELD ONLY
    Blocked: Engineer, Maintenance, Operator THREAD
    Untuk: connector_add, connector_edit
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Admin, Supervisor, Leadman - full access
        if user.role in ['admin', 'supervisor', 'leadman']:
            return view_func(request, *args, **kwargs)
        
        # Operator - check position (hanya WELD yang bisa modify)
        if user.role == 'operator':
            # Cek posisi dari operator model atau user.position
            user_position = user.user_position  # Menggunakan property dari User model
            
            if user_position == 'WELD':
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden(
                    "Access Denied: Only WELDING operators can modify Connector data. "
                    "THREADING operators cannot modify this data."
                )
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot modify Connector data."
            )
        
        # Block maintenance
        if user.role == 'maintenance':
            return HttpResponseForbidden(
                "Access Denied: Maintenance staff cannot modify Connector data."
            )
        
        # Block management
        if user.role == 'management':
            return HttpResponseForbidden(
                "Access Denied: Management cannot modify Connector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to modify Connector data."
        )
    
    return wrapper


def connector_delete_access_required(view_func):
    """
    Decorator untuk akses DELETE Connector.
    Allowed: Admin, Supervisor, Leadman
    Blocked: Operator, Engineer, Maintenance, Management
    Untuk: connector_delete
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Admin, Supervisor, Leadman - bisa delete
        if user.role in ['admin', 'supervisor', 'leadman']:
            return view_func(request, *args, **kwargs)
        
        # Block operator (walaupun WELD)
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot delete Connector data. "
                "Only Admin, Supervisor, and Leadman can delete."
            )
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot delete Connector data."
            )
        
        # Block maintenance
        if user.role == 'maintenance':
            return HttpResponseForbidden(
                "Access Denied: Maintenance staff cannot delete Connector data."
            )
        
        # Block management
        if user.role == 'management':
            return HttpResponseForbidden(
                "Access Denied: Management cannot delete Connector data."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to delete Connector data. "
            "Only Admin, Supervisor, and Leadman can delete."
        )
    
    return wrapper

def admin_required(view_func):
    """
    Decorator untuk akses Admin & Supervisor only.
    Allowed: Admin, Supervisor
    Blocked: Leadman, Operator, Engineer, Maintenance, Management
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        if not user.is_authenticated:
            return redirect('login')
        
        # Admin & Supervisor - allowed
        if user.role in ['admin', 'supervisor']:
            return view_func(request, *args, **kwargs)
        
        # Block leadman
        if user.role == 'leadman':
            return HttpResponseForbidden(
                "Access Denied: Leadman cannot access this feature. "
                "Only Admin and Supervisor can access."
            )
        
        # Block operator
        if user.role == 'operator':
            return HttpResponseForbidden(
                "Access Denied: Operators cannot access this feature. "
                "Only Admin and Supervisor can access."
            )
        
        # Block engineer
        if user.role == 'engineer':
            return HttpResponseForbidden(
                "Access Denied: Engineers cannot access this feature. "
                "Only Admin and Supervisor can access."
            )
        
        # Block maintenance
        if user.role == 'maintenance':
            return HttpResponseForbidden(
                "Access Denied: Maintenance staff cannot access this feature. "
                "Only Admin and Supervisor can access."
            )
        
        # Block management
        if user.role == 'management':
            return HttpResponseForbidden(
                "Access Denied: Management cannot access this feature. "
                "Only Admin and Supervisor can access."
            )
        
        # Jika tidak memenuhi semua kriteria
        return HttpResponseForbidden(
            "Access Denied: You don't have permission to access this feature. "
            "Only Admin and Supervisor can access."
        )
    
    return wrapper