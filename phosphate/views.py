from django.shortcuts import render, redirect
from .models import *
from production.models import *
from django.contrib import messages
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.shortcuts import get_object_or_404
from collections import defaultdict
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
import datetime, re
from django.db.models.functions import ExtractMonth, ExtractYear
import calendar
from django.db import transaction
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from functools import wraps
from django.utils import timezone

# ============================================
# CUSTOM DECORATOR FOR ROLE-BASED ACCESS
# ============================================

def phosphate_access_required(view_func):
    """
    Decorator untuk membatasi akses hanya untuk:
    - Operator
    - Supervisor
    - Admin
    - Management
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        allowed_roles = ['operator', 'supervisor', 'admin', 'management', 'leadman']
        
        if request.user.role not in allowed_roles:
            messages.error(request, "You don't have permission to access Phosphate Module. Only Operator, Supervisor, Admin, and Management can access this page.")
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================
# PHOSPHATE VIEWS - RESTRICTED ACCESS
# ============================================

@phosphate_access_required
def index(request):
    """
    Dashboard Phosphate - Menampilkan statistik phosphate untuk Box, Pin, dan Pipe
    """
    
    # ===== BOX PROTECTOR =====
    box_bjos = JobHeader.objects.filter(bjo_for='BOX PROTECTOR')
    
    box_finished = []
    box_progress = []
    
    for bjo in box_bjos:
        total_phosphated = BoxDetail.objects.filter(
            box_header__bjo=bjo,
            is_phosphated=True
        ).count()
        
        if bjo.qty and total_phosphated >= bjo.qty and total_phosphated > 0:
            box_finished.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'finish_date': BoxHeader.objects.filter(bjo=bjo).order_by('-created_at').first().created_at.date() if BoxHeader.objects.filter(bjo=bjo).exists() else None
            })
        elif bjo.qty and 0 < total_phosphated < bjo.qty:
            box_progress.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'remaining_qty': bjo.qty - total_phosphated
            })
    
    # ===== PIN PROTECTOR =====
    pin_bjos = JobHeader.objects.filter(bjo_for='PIN PROTECTOR')
    
    pin_finished = []
    pin_progress = []
    
    for bjo in pin_bjos:
        total_phosphated = PinDetail.objects.filter(
            pin_header__bjo=bjo,
            is_phosphated=True
        ).count()
        
        if bjo.qty and total_phosphated >= bjo.qty and total_phosphated > 0:
            pin_finished.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'finish_date': PinHeader.objects.filter(bjo=bjo).order_by('-created_at').first().created_at.date() if PinHeader.objects.filter(bjo=bjo).exists() else None
            })
        elif bjo.qty and 0 < total_phosphated < bjo.qty:
            pin_progress.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'remaining_qty': bjo.qty - total_phosphated
            })
    
    # ===== PIPE =====
    pipe_bjos = JobHeader.objects.filter(bjo_for='PIPE')
    
    pipe_finished = []
    pipe_progress = []
    
    for bjo in pipe_bjos:
        # Untuk pipe, kita hitung berdasarkan joint yang sudah di-phosphate (baik box atau pin)
        total_phosphated = PipePhosphateDetail.objects.filter(
            pipephosphate_header__bjo=bjo
        ).values('joint_number').distinct().count()
        
        if bjo.qty and total_phosphated >= bjo.qty * 2 and total_phosphated > 0:  # *2 karena setiap joint ada box dan pin
            pipe_finished.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'finish_date': PipePhosphateHeader.objects.filter(bjo=bjo).order_by('-created_at').first().created_at.date() if PipePhosphateHeader.objects.filter(bjo=bjo).exists() else None
            })
        elif bjo.qty and 0 < total_phosphated < bjo.qty * 2:
            pipe_progress.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_phosphated': total_phosphated,
                'remaining_qty': (bjo.qty * 2) - total_phosphated
            })
    
    # ===== STATISTICS =====
    stats = {
        # Box Protector
        'box_total_finished': len(box_finished),
        'box_total_progress': len(box_progress),
        
        # Pin Protector
        'pin_total_finished': len(pin_finished),
        'pin_total_progress': len(pin_progress),
        
        # Pipe
        'pipe_total_finished': len(pipe_finished),
        'pipe_total_progress': len(pipe_progress),
    }
    
    context = {
        # Box Protector
        'box_finished': sorted(box_finished, key=lambda x: x['finish_date'] or timezone.now().date(), reverse=True)[:5],
        'box_progress': box_progress[:5],
        
        # Pin Protector
        'pin_finished': sorted(pin_finished, key=lambda x: x['finish_date'] or timezone.now().date(), reverse=True)[:5],
        'pin_progress': pin_progress[:5],
        
        # Pipe
        'pipe_finished': sorted(pipe_finished, key=lambda x: x['finish_date'] or timezone.now().date(), reverse=True)[:5],
        'pipe_progress': pipe_progress[:5],
        
        'stats': stats,
    }
    
    return render(request, 'phosphate/index.html', context)


# ============================================
# BOX PROTECTOR PHOSPHATE VIEWS
# ============================================

@phosphate_access_required
def box_phosphate_header(request):
    """Create new BOX Phosphate header"""
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="BOX PROTECTOR")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in BoxHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')

        if bjo_id and station and shift_id and operator_id:
            job = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)

            new_header = BoxHeader.objects.create(
                bjo=job,
                station=station,
                shift=shift,
                operator=operator
            )

            return redirect('box_phosphate_detail', header_id=new_header.id)

    context = {
        'active_menu': 'box_phosphate',
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
    }

    return render(request, 'box/header.html', context)


@phosphate_access_required
def box_phosphate_edit(request, header_id):
    """Edit BOX Protector Phosphated"""
    box = get_object_or_404(BoxHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_id = request.POST.get('bjo')
            station = request.POST.get('station')
            shift_id = request.POST.get('shift')
            operator_id = request.POST.get('operator')
            
            if bjo_id and station and shift_id and operator_id:
                job = JobHeader.objects.get(id=bjo_id)
                shift = Shift.objects.get(id=shift_id)
                operator = Operator.objects.get(id=operator_id)
                
                box.bjo = job
                box.station = station
                box.shift = shift
                box.operator = operator
                box.save()
                
                messages.success(request, f'Data BOX untuk BJO {box.bjo.bjo} berhasil diupdate!')
                return redirect('box_phosphate_summary')
            else:
                messages.error(request, 'Semua field harus diisi!')
                return redirect('box_phosphate_edit', header_id=header_id)
            
        except Exception as e:
            messages.error(request, f'Error saat update data: {str(e)}')
            return redirect('box_phosphate_edit', header_id=header_id)
    
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="BOX PROTECTOR")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in BoxHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()
    
    context = {
        'box': box,
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
        'active_menu': 'box_phosphate_summary',
    }
    
    return render(request, 'box/box_phosphate_edit.html', context)


@phosphate_access_required
def box_phosphate_delete(request, header_id):
    """Delete BOX Protector Phosphated"""
    box = get_object_or_404(BoxHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_name = box.bjo.bjo if box.bjo else 'Unknown'
            BoxDetail.objects.filter(box_header=box).delete()
            box.delete()
            messages.success(request, f'BOX record for BJO {bjo_name} has been deleted successfully!')
        except Exception as e:
            messages.error(request, f'Error deleting record: {str(e)}')
    
    return redirect('box_phosphate_summary')


@phosphate_access_required
def box_phosphate_detail(request, header_id):
    """
    Add BOX Protector details to phosphate record
    Shows only BOX that:
    - Already threaded (is_threaded=True)
    - Not yet phosphated in any header
    - Belongs to the same BJO
    """
    header = get_object_or_404(BoxHeader, id=header_id)

    # Get IDs of BOX that already phosphated in any header
    already_phosphated_ids = BoxDetail.objects.all().values_list('protector_number_id', flat=True)
    
    # Filter BOX: threaded, same BJO, not yet phosphated
    box_list = BoxProtector.objects.filter(
        is_threaded=True,
        bjo=header.bjo
    ).exclude(
        id__in=already_phosphated_ids
    ).order_by('serial_number')

    if request.method == 'POST':
        box_id = request.POST.get('bjo')
        if box_id:
            try:
                protector = BoxProtector.objects.get(id=box_id)
                
                # Double check: prevent duplicate phosphate
                existing = BoxDetail.objects.filter(
                    protector_number=protector
                ).exists()
                
                if existing:
                    messages.error(
                        request, 
                        f"BOX {protector.serial_number} sudah pernah di-phosphate sebelumnya."
                    )
                else:
                    # Create phosphate detail
                    BoxDetail.objects.create(
                        box_header=header,
                        protector_number=protector,
                        is_phosphated=True 
                    )
                    
                    # Mark as used
                    protector.is_used = True
                    protector.save()
                    
                    messages.success(
                        request, 
                        f"BOX {protector.serial_number} berhasil ditambahkan."
                    )
                    
            except BoxProtector.DoesNotExist:
                messages.error(request, "BOX tidak ditemukan.")

            return redirect('box_phosphate_detail', header_id=header.id)

    context = {
        'active_menu': 'box_phosphate',
        'header': header,
        'box_list': box_list
    }

    return render(request, 'box/detail.html', context)


@phosphate_access_required
def box_phosphate_detail_delete(request, detail_id):
    """Delete box phosphate detail and revert protector status"""
    detail = get_object_or_404(BoxDetail, id=detail_id)
    header_id = detail.box_header.id
    
    protector = detail.protector_number
    protector.is_used = False
    protector.save()
    
    detail.delete()
    
    messages.success(request, f"Data {protector.serial_number} berhasil dihapus dan status protector dikembalikan.")
    
    return redirect('box_phosphate_detail', header_id=header_id)


@phosphate_access_required
def box_phosphate_report(request, header_id):
    """Generate BOX Phosphate report"""
    selected_headers = get_object_or_404(
        BoxHeader.objects.select_related('operator', 'shift')
        .prefetch_related('box_details__protector_number'), 
        id=header_id
    )
    context = {
        'active_menu': 'box_report',
        'selected_headers': selected_headers
    }
    return render(request, 'box/report.html', context)


@phosphate_access_required
def box_phosphate_summary(request):
    """Summary/list BOX Protector Phosphated with details count"""
    from django.db.models import Count, Q, Sum, Case, When, IntegerField, Value
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_station = request.GET.get('station', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    all_bp = BoxHeader.objects.select_related('bjo', 'operator', 'shift').annotate(
        total_boxes=Count('box_details__id', distinct=True),
        boxes_phosphated=Sum(
            Case(
                When(box_details__is_phosphated=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        boxes_installed=Sum(
            Case(
                When(box_details__is_installed=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    ).all()

    if query:
        all_bp = all_bp.filter(
            Q(bjo__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    if filter_bjo:
        try:
            all_bp = all_bp.filter(bjo__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass

    if filter_station:
        all_bp = all_bp.filter(station=filter_station)

    if filter_shift:
        try:
            all_bp = all_bp.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass

    if filter_year:
        try:
            all_bp = all_bp.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass

    if filter_month and filter_year:
        try:
            all_bp = all_bp.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass

    if filter_date:
        try:
            date_obj = datetime.datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_bp = all_bp.filter(created_at__date=date_obj)
        except ValueError:
            pass

    all_bp = all_bp.order_by('-id')

    paginator = Paginator(all_bp, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    try:
        bjo_options = BoxHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    try:
        station_options = BoxHeader.objects.filter(
            station__isnull=False
        ).exclude(
            station=''
        ).values_list('station', flat=True).distinct().order_by('station')
    except Exception:
        station_options = []
    
    try:
        shift_options = BoxHeader.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    try:
        year_options = BoxHeader.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_bp': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_station': filter_station,
        'filter_shift': filter_shift,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'bjo_options': bjo_options,
        'station_options': station_options,
        'shift_options': shift_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'box_phosphate_summary',
    }

    return render(request, 'box/box_phosphate_summary.html', context)


@phosphate_access_required
def box_phosphate_summary_detail(request, header_id):
    """Detail view for BOX Phosphate summary"""
    header = get_object_or_404(
        BoxHeader.objects
        .select_related('bjo', 'operator')
        .prefetch_related('box_details__protector_number', 'box_details__installed_to'),
        pk=header_id
    )

    context = {
        'active_menu': 'box_phosphate_summary',
        'header': header,
        'details': header.box_details.all()
    }
    return render(request, 'box/box_phosphate_summary_detail.html', context)


@phosphate_access_required
def box_report_all(request):
    """Generate all BOX reports with filter"""
    month = request.GET.get('month')
    year = request.GET.get('year')

    details = (
        BoxDetail.objects
        .select_related(
            'box_header',
            'box_header__operator',
            'box_header__shift',
            'protector_number',
            'installed_to',
        )
    )

    if month and year:
        details = details.filter(
            box_header__created_at__month=month,
            box_header__created_at__year=year
        )

    details = details.order_by('box_header__created_at')

    report_data = [
        {
            'no': idx,
            'date': detail.box_header.created_at,
            'bp_no': detail.protector_number if detail.protector_number else '',
            'operator': detail.box_header.operator.name if detail.box_header.operator else '',
            'shift': detail.box_header.shift.name if detail.box_header.shift else '',
            'installed_to': detail.installed_to.joint_number if detail.installed_to else 'NOT YET',
        }
        for idx, detail in enumerate(details, start=1)
    ]

    current_year = datetime.date.today().year
    years = list(range(current_year - 5, current_year + 1))
    months = [
        {'num': 1, 'name': 'January'},
        {'num': 2, 'name': 'February'},
        {'num': 3, 'name': 'March'},
        {'num': 4, 'name': 'April'},
        {'num': 5, 'name': 'May'},
        {'num': 6, 'name': 'June'},
        {'num': 7, 'name': 'July'},
        {'num': 8, 'name': 'August'},
        {'num': 9, 'name': 'September'},
        {'num': 10, 'name': 'October'},
        {'num': 11, 'name': 'November'},
        {'num': 12, 'name': 'December'},
    ]

    context = {
        'report_data': report_data,
        'months': months,
        'years': years,
        'selected_month': int(month) if month else '',
        'selected_year': int(year) if year else '',
    }
    return render(request, 'box/box_report.html', context)


# ============================================
# PIN PROTECTOR PHOSPHATE VIEWS
# ============================================

@phosphate_access_required
def pin_phosphate_header(request):
    """Create new PIN Phosphate header"""
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIN PROTECTOR")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PinHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')

        if bjo_id and station and shift_id and operator_id:
            job = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)

            new_header = PinHeader.objects.create(
                bjo=job,
                station=station,
                shift=shift,
                operator=operator
            )

            return redirect('pin_phosphate_detail', header_id=new_header.id)

    context = {
        'active_menu': 'pin_phosphate',
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
    }
    return render(request, 'pin/header.html', context)


@phosphate_access_required
def pin_phosphate_detail(request, header_id):
    """
    Add PIN Protector details to phosphate record
    Shows only PIN that:
    - Already threaded (is_threaded=True)
    - Not yet phosphated in any header
    - Belongs to the same BJO
    """
    header = get_object_or_404(PinHeader, id=header_id)

    # ✅ FIXED: Exclude PIN yang sudah di-phosphate di header manapun
    already_phosphated_ids = PinDetail.objects.all().values_list('protector_number_id', flat=True)
    
    pin_list = PinProtector.objects.filter(
        is_threaded=True,
        bjo=header.bjo
    ).exclude(
        id__in=already_phosphated_ids  # ✅ Exclude yang sudah phosphated
    ).order_by('serial_number')

    if request.method == 'POST':
        pin_id = request.POST.get('bjo')
        if pin_id:
            try:
                protector = PinProtector.objects.get(id=pin_id)
                
                # ✅ Double check: prevent duplicate phosphate
                existing = PinDetail.objects.filter(
                    protector_number=protector
                ).exists()
                
                if existing:
                    messages.error(
                        request, 
                        f"PIN {protector.serial_number} sudah pernah di-phosphate sebelumnya."
                    )
                else:
                    # Create phosphate detail
                    PinDetail.objects.create(
                        pin_header=header,
                        protector_number=protector,
                        is_phosphated=True
                    )
                    
                    # Mark as used
                    protector.is_used = True
                    protector.save()
                    
                    messages.success(
                        request, 
                        f"PIN {protector.serial_number} berhasil ditambahkan."
                    )
                    
            except PinProtector.DoesNotExist:
                messages.error(request, "PIN tidak ditemukan.")
           
            return redirect('pin_phosphate_detail', header_id=header.id)

    context = {
        'active_menu': 'pin_phosphate',
        'header': header,
        'pin_list': pin_list
    }
    return render(request, 'pin/detail.html', context)


@phosphate_access_required
def pin_phosphate_detail_delete(request, detail_id):
    """Delete pin phosphate detail and revert protector status"""
    detail = get_object_or_404(PinDetail, id=detail_id)
    header_id = detail.pin_header.id
    
    serial_number = detail.protector_number.serial_number
    was_installed = detail.is_installed
    
    protector = detail.protector_number
    protector.is_used = False
    protector.save()
    
    detail.delete()
    
    if was_installed:
        messages.warning(request, f"Data {serial_number} berhasil dihapus. Status protector dan instalasi telah dikembalikan.")
    else:
        messages.success(request, f"Data {serial_number} berhasil dihapus dan status protector dikembalikan.")
    
    return redirect('pin_phosphate_detail', header_id=header_id)


@phosphate_access_required
def pin_phosphate_report(request, header_id):
    """Generate PIN Phosphate report"""
    selected_headers = get_object_or_404(
        PinHeader.objects.select_related('operator', 'shift')
        .prefetch_related('pin_details__protector_number'), 
        id=header_id
    )
    context = {
        'active_menu': 'pin_report',
        'selected_headers': selected_headers
    }
    return render(request, 'pin/report.html', context)


@phosphate_access_required
def pin_phosphate_summary(request):
    """Summary/list PIN Protector Phosphated with details count"""
    from django.db.models import Count, Q, Sum, Case, When, IntegerField, Value
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_station = request.GET.get('station', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    all_pin = PinHeader.objects.select_related('bjo', 'operator', 'shift').annotate(
        total_pins=Count('pin_details__id', distinct=True),
        pins_phosphated=Sum(
            Case(
                When(pin_details__is_phosphated=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        pins_installed=Sum(
            Case(
                When(pin_details__is_installed=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    ).all()

    if query:
        all_pin = all_pin.filter(
            Q(bjo__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    if filter_bjo:
        try:
            all_pin = all_pin.filter(bjo__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass

    if filter_station:
        all_pin = all_pin.filter(station=filter_station)

    if filter_shift:
        try:
            all_pin = all_pin.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass

    if filter_year:
        try:
            all_pin = all_pin.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass

    if filter_month and filter_year:
        try:
            all_pin = all_pin.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass

    if filter_date:
        try:
            date_obj = datetime.datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_pin = all_pin.filter(created_at__date=date_obj)
        except ValueError:
            pass

    all_pin = all_pin.order_by('-id')

    paginator = Paginator(all_pin, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    try:
        bjo_options = PinHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    try:
        station_options = PinHeader.objects.filter(
            station__isnull=False
        ).exclude(
            station=''
        ).values_list('station', flat=True).distinct().order_by('station')
    except Exception:
        station_options = []
    
    try:
        shift_options = PinHeader.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    try:
        year_options = PinHeader.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_pin': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_station': filter_station,
        'filter_shift': filter_shift,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'bjo_options': bjo_options,
        'station_options': station_options,
        'shift_options': shift_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'pin_phosphate_summary',
    }

    return render(request, 'pin/pin_phosphate_summary.html', context)


@phosphate_access_required
def pin_phosphate_edit(request, header_id):
    """Edit PIN Protector Phosphated"""
    pin = get_object_or_404(PinHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_id = request.POST.get('bjo')
            station = request.POST.get('station')
            shift_id = request.POST.get('shift')
            operator_id = request.POST.get('operator')
            
            if bjo_id and station and shift_id and operator_id:
                job = JobHeader.objects.get(id=bjo_id)
                shift = Shift.objects.get(id=shift_id)
                operator = Operator.objects.get(id=operator_id)
                
                pin.bjo = job
                pin.station = station
                pin.shift = shift
                pin.operator = operator
                pin.save()
                
                messages.success(request, f'Data PIN untuk BJO {pin.bjo.bjo} berhasil diupdate!')
                return redirect('pin_phosphate_summary')
            else:
                messages.error(request, 'Semua field harus diisi!')
                return redirect('pin_phosphate_edit', header_id=header_id)
            
        except Exception as e:
            messages.error(request, f'Error saat update data: {str(e)}')
            return redirect('pin_phosphate_edit', header_id=header_id)
    
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIN PROTECTOR")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PinHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()
    
    context = {
        'pin': pin,
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
        'active_menu': 'pin_phosphate_summary',
    }
    
    return render(request, 'pin/pin_phosphate_edit.html', context)


@phosphate_access_required
def pin_phosphate_delete(request, header_id):
    """Delete PIN Protector Phosphated"""
    pin = get_object_or_404(PinHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_name = pin.bjo.bjo
            PinDetail.objects.filter(pin_header=pin).delete()
            pin.delete()
            messages.success(request, f'Data PIN untuk BJO {bjo_name} berhasil dihapus!')
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
    
    return redirect('pin_phosphate_summary')


@phosphate_access_required
def pin_phosphate_summary_detail(request, header_id):
    """Detail view for PIN Phosphate summary"""
    header = get_object_or_404(
        PinHeader.objects
        .select_related('bjo', 'operator')
        .prefetch_related('pin_details__protector_number', 'pin_details__installed_to'),
        pk=header_id
    )

    context = {
        'active_menu': 'pin_phosphate_summary',
        'header': header,
        'details': header.pin_details.all()
    }
    return render(request, 'pin/pin_phosphate_summary_detail.html', context)


@phosphate_access_required
def pin_report(request):
    """Generate all PIN reports with filter"""
    month = request.GET.get('month')
    year = request.GET.get('year')

    details = (
        PinDetail.objects
        .select_related(
            'pin_header',
            'pin_header__operator',
            'pin_header__shift',
            'protector_number',
            'installed_to'
        )
    )

    if month and year:
        details = details.filter(
            pin_header__created_at__month=month,
            pin_header__created_at__year=year
        )

    details = details.order_by('pin_header__created_at')

    report_data = [
        {
            'no': idx,
            'date': detail.pin_header.created_at,
            'bp_no': detail.protector_number if detail.protector_number else '',
            'operator': detail.pin_header.operator.name if detail.pin_header.operator else '',
            'shift': detail.pin_header.shift.name if detail.pin_header.shift else '',
            'installed_to': detail.installed_to.joint_number if detail.installed_to else 'NOT YET',
        }
        for idx, detail in enumerate(details, start=1)
    ]

    current_year = datetime.date.today().year
    years = list(range(current_year - 5, current_year + 1))
    months = [
        {'num': 1, 'name': 'January'},
        {'num': 2, 'name': 'February'},
        {'num': 3, 'name': 'March'},
        {'num': 4, 'name': 'April'},
        {'num': 5, 'name': 'May'},
        {'num': 6, 'name': 'June'},
        {'num': 7, 'name': 'July'},
        {'num': 8, 'name': 'August'},
        {'num': 9, 'name': 'September'},
        {'num': 10, 'name': 'October'},
        {'num': 11, 'name': 'November'},
        {'num': 12, 'name': 'December'},
    ]

    context = {
        'report_data': report_data,
        'months': months,
        'years': years,
        'selected_month': int(month) if month else '',
        'selected_year': int(year) if year else '',
    }
    return render(request, 'reports/pin_report.html', context)


@phosphate_access_required
def export_pin_pdf(request):
    """Export PIN report to PDF"""
    pin_details = PinDetail.objects.select_related('protector_number', 'installed_to').all()
    template = get_template('pin/pin_report_pdf.html')
    html = template.render({'pin_details': pin_details})

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="pin_report.pdf"'
    pisa_status = pisa.CreatePDF(html, dest=response)
    return response


@phosphate_access_required
# proses phosphate pipa
def pipe_phosphate_header(request):
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIPE")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PinHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')

        if bjo_id and station and shift_id and operator_id:
            job = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)

            # Simpan ke model PinPhosphate Header
            new_header = PipePhosphateHeader.objects.create(
                bjo=job,
                station=station,
                shift=shift,
                operator=operator
            )

            return redirect('pipe_phosphate_detail', header_id=new_header.id)

    context = {
        'active_menu':'pipe_phosphate',
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
    }

    return render(request, 'pipe/header.html', context)

@phosphate_access_required
def pipe_phosphate_detail(request, header_id):
    """
    View untuk menampilkan detail dan menambahkan joint baru
    Logic: 
    - Joint bisa punya BOX dan PIN side terpisah
    - Satu side hanya boleh di-phosphate 1x
    - Filter hanya tampilkan joint yang minimal 1 side sudah threaded tapi belum phosphated
    """
    header = get_object_or_404(PipePhosphateHeader, id=header_id)

    # ✅ FIXED: Filter joint yang masih ada side yang belum di-phosphate
    pipe_list = SerialNumber.objects.filter(
        bjo=header.bjo
    ).filter(
        # Minimal 1 side sudah threaded
        Q(is_box_threaded=True) | Q(is_pin_threaded=True)
    ).filter(
        # Dan minimal 1 side belum phosphated
        Q(is_box_phosphated=False) | Q(is_pin_phosphated=False)
    ).order_by('joint_number')

    if request.method == 'POST':
        joint_id = request.POST.get('joint_number')
        side = request.POST.get('side_phosphate')

        if not joint_id or not side:
            messages.error(request, "Joint number dan sisi phosphate wajib diisi.")
            return redirect('pipe_phosphate_detail', header_id=header.id)

        try:
            joint = SerialNumber.objects.get(id=joint_id)
        except SerialNumber.DoesNotExist:
            messages.error(request, "Joint number tidak ditemukan.")
            return redirect('pipe_phosphate_detail', header_id=header.id)

        # ✅ Validasi: sisi yang dipilih harus sudah di-threaded
        if side == 'BOX' and not joint.is_box_threaded:
            messages.error(request, f"Sisi BOX pada joint {joint.joint_number} belum di-threaded.")
            return redirect('pipe_phosphate_detail', header_id=header.id)
        
        if side == 'PIN' and not joint.is_pin_threaded:
            messages.error(request, f"Sisi PIN pada joint {joint.joint_number} belum di-threaded.")
            return redirect('pipe_phosphate_detail', header_id=header.id)

        # ✅ Validasi: cek apakah sisi ini sudah pernah di-phosphate (di header manapun)
        if side == 'BOX' and joint.is_box_phosphated:
            messages.error(
                request, 
                f"Sisi BOX pada joint {joint.joint_number} sudah pernah di-phosphate sebelumnya."
            )
            return redirect('pipe_phosphate_detail', header_id=header.id)
        
        if side == 'PIN' and joint.is_pin_phosphated:
            messages.error(
                request, 
                f"Sisi PIN pada joint {joint.joint_number} sudah pernah di-phosphate sebelumnya."
            )
            return redirect('pipe_phosphate_detail', header_id=header.id)

        # ✅ Cek apakah sudah ada record untuk joint ini di header yang sama
        existing_detail = PipePhosphateDetail.objects.filter(
            pipephosphate_header=header,
            joint_number=joint
        ).first()

        if existing_detail:
            # UPDATE: Joint sudah ada di header ini, tambahkan side yang baru
            current_sides = existing_detail.side_phosphate or ''
            
            # Cek apakah side ini sudah ada di record
            if side in current_sides.split(','):
                messages.warning(
                    request, 
                    f"Sisi {side} untuk joint {joint.joint_number} sudah ada di record ini."
                )
            else:
                # Tambahkan side baru
                if current_sides:
                    existing_detail.side_phosphate = f"{current_sides},{side}"
                else:
                    existing_detail.side_phosphate = side
                existing_detail.save()
                
                # Update SerialNumber status
                if side == 'BOX':
                    joint.is_box_phosphated = True
                elif side == 'PIN':
                    joint.is_pin_phosphated = True
                joint.save()
                
                messages.success(
                    request, 
                    f"Joint {joint.joint_number} sisi {side} berhasil di-update."
                )
        else:
            # INSERT: Buat record baru untuk joint ini
            PipePhosphateDetail.objects.create(
                pipephosphate_header=header,
                joint_number=joint,
                side_phosphate=side
            )
            
            # Update SerialNumber status
            if side == 'BOX':
                joint.is_box_phosphated = True
            elif side == 'PIN':
                joint.is_pin_phosphated = True
            joint.save()
            
            messages.success(
                request, 
                f"Joint {joint.joint_number} sisi {side} berhasil disimpan."
            )

        return redirect('pipe_phosphate_detail', header_id=header.id)

    context = {
        'active_menu': 'pipe_phosphate',
        'header': header,
        'pipe_list': pipe_list,
    }

    return render(request, 'pipe/detail.html', context)

@phosphate_access_required
def pipe_phosphate_detail_delete(request, detail_id):
    """
    Delete pipe phosphate detail and revert ALL phosphate status
    """
    detail = get_object_or_404(PipePhosphateDetail, id=detail_id)
    header_id = detail.pipephosphate_header.id
    joint = detail.joint_number
    
    # Simpan info untuk pesan
    joint_number = joint.joint_number
    sides_reverted = []
    
    # Revert SEMUA status phosphate yang ada di record ini
    sides = detail.side_phosphate.split(',')
    
    for side in sides:
        side = side.strip()
        if side == 'BOX':
            joint.is_box_phosphated = False
            sides_reverted.append("BOX")
        elif side == 'PIN':
            joint.is_pin_phosphated = False
            sides_reverted.append("PIN")
    
    joint.save()
    
    # Delete detail
    detail.delete()
    
    # Pesan yang informatif
    sides_text = " & ".join(sides_reverted) if sides_reverted else "No side"
    messages.success(request, f"Data joint {joint_number} ({sides_text}) berhasil dihapus dan status dikembalikan.")
    
    return redirect('pipe_phosphate_detail', header_id=header_id)

@phosphate_access_required
def pipe_phosphate_update(request, header_id, detail_id):
    """
    View untuk update sisi yang belum di-phosphate pada joint yang sudah ada
    """
    if request.method != 'POST':
        return redirect('pipe_phosphate_detail', header_id=header_id)
    
    header = get_object_or_404(PipePhosphateHeader, id=header_id)
    detail = get_object_or_404(PipePhosphateDetail, id=detail_id, pipephosphate_header=header)
    
    side = request.POST.get('side_phosphate')
    
    if not side or side not in ['BOX', 'PIN']:
        messages.error(request, "Sisi phosphate tidak valid.")
        return redirect('pipe_phosphate_detail', header_id=header.id)
    
    joint = detail.joint_number
    
    # Validasi: sisi yang dipilih harus sudah di-threaded
    if side == 'BOX' and not joint.is_box_threaded:
        messages.error(request, f"Sisi BOX pada joint {joint.joint_number} belum di-threaded.")
        return redirect('pipe_phosphate_detail', header_id=header.id)
    
    if side == 'PIN' and not joint.is_pin_threaded:
        messages.error(request, f"Sisi PIN pada joint {joint.joint_number} belum di-threaded.")
        return redirect('pipe_phosphate_detail', header_id=header.id)
    
    # Validasi: pastikan sisi yang akan di-update belum di-phosphate
    if side == 'BOX' and joint.is_box_phosphated:
        messages.error(request, f"Sisi BOX pada joint {joint.joint_number} sudah di-phosphate.")
        return redirect('pipe_phosphate_detail', header_id=header.id)
    
    if side == 'PIN' and joint.is_pin_phosphated:
        messages.error(request, f"Sisi PIN pada joint {joint.joint_number} sudah di-phosphate.")
        return redirect('pipe_phosphate_detail', header_id=header.id)
    
    # Update record yang sudah ada (TIDAK membuat record baru)
    # Update SerialNumber
    if side == 'BOX':
        joint.is_box_phosphated = True
    elif side == 'PIN':
        joint.is_pin_phosphated = True
    joint.save()
    
    # Update detail side_phosphate field
    current_sides = detail.side_phosphate
    if side not in current_sides:
        detail.side_phosphate = f"{current_sides},{side}" if current_sides else side
        detail.save()
    
    messages.success(request, f"Sisi {side} untuk joint {joint.joint_number} berhasil di-update.")
    return redirect('pipe_phosphate_detail', header_id=header.id)

@phosphate_access_required
def pipe_phosphate_report(request, header_id):
    selected_header = get_object_or_404(
        PipePhosphateHeader.objects
        .select_related('operator', 'shift')
        .prefetch_related('pipephosphate_details__joint_number'),
        id=header_id
    )

    # Buat dict gabungan berdasarkan joint_number
    merged_details = defaultdict(lambda: {'joint_number': None, 'box': False, 'pin': False})

    for detail in selected_header.pipephosphate_details.all():
        key = detail.joint_number.joint_number  # atau field unik lain dari joint_number
        merged_details[key]['joint_number'] = detail.joint_number
        if detail.box_phosphated:
            merged_details[key]['box'] = True
        if detail.pin_phosphated:
            merged_details[key]['pin'] = True

    # Convert ke list supaya bisa di-loop di template
    combined_details = list(merged_details.values())

    context = {
        'active_menu': 'pipe_phosphate_report',
        'selected_header': selected_header,
        'combined_details': combined_details,
    }
    return render(request, 'pipe/report.html', context)

@phosphate_access_required
def pipe_phosphate_report_pdf(request, header_id):
    header = get_object_or_404(
        PipePhosphateHeader.objects
        .select_related('operator', 'shift')
        .prefetch_related('pipephosphate_details__joint_number'),
        id=header_id
    )

    # Gabungkan detail berdasarkan joint_number
    merged = defaultdict(lambda: {'joint_number': None, 'box': False, 'pin': False})
    for detail in header.pipephosphate_details.all():
        key = detail.joint_number_id  # Gunakan ID agar lebih efisien
        merged[key]['joint_number'] = detail.joint_number
        if detail.box_phosphated:
            merged[key]['box'] = True
        if detail.pin_phosphated:
            merged[key]['pin'] = True
    combined = list(merged.values())

    # PDF setup
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Fungsi untuk pewarnaan teks
    def colored_status(text, color):
        return Paragraph(f'<font color="{color}">{text}</font>', styles['Normal'])

    # Judul
    elements.append(Paragraph("Laporan PIPE Phosphate", styles['Title']))
    elements.append(Spacer(1, 12))

    # Header Info
    info = f"""
    <b>Tanggal:</b> {header.created_at.strftime('%d %b %Y')}<br/>
    <b>Operator:</b> {header.operator.name}<br/>
    <b>Shift:</b> {header.shift.name}<br/>
    <b>Area Kerja:</b> {header.station}<br/>
    """
    elements.append(Paragraph(info, styles['Normal']))
    elements.append(Spacer(1, 12))

    # Tabel Data
    data = [['No.', 'No. Joint', 'Sisi BOX', 'Sisi PIN', 'Status']]
    for i, row in enumerate(combined, 1):
        box_status = colored_status('Sudah di phosphate', 'blue') if row['box'] else colored_status('Belum di phosphate', 'red')
        pin_status = colored_status('Sudah di phosphate', 'blue') if row['pin'] else colored_status('Belum di phosphate', 'red')
        overall_status = colored_status('Sudah Komplit', 'blue') if row['box'] and row['pin'] else colored_status('Belum Komplit', 'red')
        
        data.append([
            i,
            str(row['joint_number']),
            box_status,
            pin_status,
            overall_status
        ])

    # Table styling
    table = Table(data, colWidths=[40, 120, 120, 120, 120])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    # Response
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="laporan_pipe_{header.id}.pdf"'
    return response

@phosphate_access_required
def pipe_phosphate_report_all(request):
    month = request.GET.get("month")
    year = request.GET.get("year")

    # Ambil semua data header
    headers = PipePhosphateHeader.objects.all()

    # Ambil daftar bulan & tahun dari database
    months_available = headers.annotate(month_val=ExtractMonth('created_at')) \
                              .values_list('month_val', flat=True).distinct()
    years_available = headers.annotate(year_val=ExtractYear('created_at')) \
                             .values_list('year_val', flat=True).distinct()

    # Filter jika bulan & tahun dipilih
    if month:
        headers = headers.annotate(month_val=ExtractMonth('created_at')).filter(month_val=month)
    if year:
        headers = headers.annotate(year_val=ExtractYear('created_at')).filter(year_val=year)

    # Proses data supaya joint number unik (BOX & PIN di-merge)
    report_data = []
    seen_joints = set()
    counter = 1

    for header in headers:
        details = header.pipephosphate_details.all()
        for detail in details:
            joint_key = detail.joint_number

            if joint_key not in seen_joints:
                seen_joints.add(joint_key)
                has_box = details.filter(joint_number=detail.joint_number, box_phosphated=True).exists()
                has_pin = details.filter(joint_number=detail.joint_number, pin_phosphated=True).exists()

                report_data.append({
                    "no": counter,
                    "date": header.created_at,
                    "joint_number": joint_key,
                    "station": header.station,
                    "shift": header.shift,
                    "operator": header.operator.name,
                    "box_phosphated": '<span style="color:green;">&#10004;</span>' if has_box else '<span style="color:red;">&#10008;</span>',
                    "pin_phosphated": '<span style="color:green;">&#10004;</span>' if has_pin else '<span style="color:red;">&#10008;</span>'
                })
                counter += 1

    context = {
        "report_data": report_data,
        "months_available": sorted([(m, calendar.month_name[m]) for m in months_available if m]),
        "years_available": sorted(years_available, reverse=True),
        "month": month,
        "year": year
    }
    return render(request, "pipe/pipe_phosphate_report.html", context)

@phosphate_access_required
def pipe_phosphate_summary(request):
    """
    View untuk menampilkan summary/list data PIPE Protector Phosphated dengan jumlah detail
    """
    from django.db.models import Count, Q, Sum, Case, When, IntegerField, Value
    
    # Ambil parameter filter dengan validasi
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_station = request.GET.get('station', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    # Query dasar dengan annotate untuk hitung detail
    # Hitung unique joint_number (bukan total records)
    all_pipe = PipePhosphateHeader.objects.select_related('bjo', 'operator', 'shift').annotate(
        # Total unique joints
        total_joints=Count('pipephosphate_details__joint_number', distinct=True),
        # BOX yang sudah di-phosphate
        box_phosphated=Sum(
            Case(
                When(pipephosphate_details__box_phosphated=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        # PIN yang sudah di-phosphate
        pin_phosphated=Sum(
            Case(
                When(pipephosphate_details__pin_phosphated=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    ).all()

    # Filter pencarian (hanya jika query tidak kosong)
    if query:
        all_pipe = all_pipe.filter(
            Q(bjo__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    # Filter BJO (hanya jika tidak kosong)
    if filter_bjo:
        try:
            all_pipe = all_pipe.filter(bjo__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter Station (hanya jika tidak kosong)
    if filter_station:
        all_pipe = all_pipe.filter(station=filter_station)

    # Filter Shift (hanya jika tidak kosong)
    if filter_shift:
        try:
            all_pipe = all_pipe.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tahun
    if filter_year:
        try:
            all_pipe = all_pipe.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan bulan (membutuhkan tahun juga)
    if filter_month and filter_year:
        try:
            all_pipe = all_pipe.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_pipe = all_pipe.filter(created_at__date=date_obj)
        except ValueError:
            pass  # Ignore invalid date format

    all_pipe = all_pipe.order_by('-id')

    # Pagination
    paginator = Paginator(all_pipe, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opsi untuk dropdown dengan error handling
    try:
        bjo_options = PipePhosphateHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    try:
        station_options = PipePhosphateHeader.objects.filter(
            station__isnull=False
        ).exclude(
            station=''
        ).values_list('station', flat=True).distinct().order_by('station')
    except Exception:
        station_options = []
    
    try:
        # Ambil shift options dengan ID dan nama
        shift_options = PipePhosphateHeader.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    # Opsi tahun berdasarkan data yang ada
    try:
        year_options = PipePhosphateHeader.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    # Opsi bulan (1-12)
    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_pipe': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_station': filter_station,
        'filter_shift': filter_shift,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'bjo_options': bjo_options,
        'station_options': station_options,
        'shift_options': shift_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'pipe_phosphate_summary',
    }

    return render(request, 'pipe/pipe_phosphate_summary.html', context)

@phosphate_access_required
def pipe_phosphate_edit(request, header_id):
    """
    View untuk edit PIPE Protector Phosphated
    """
    pipe = get_object_or_404(PipePhosphateHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            # Ambil data dari form
            bjo_id = request.POST.get('bjo')
            station = request.POST.get('station')
            shift_id = request.POST.get('shift')
            operator_id = request.POST.get('operator')
            
            # Validasi data
            if bjo_id and station and shift_id and operator_id:
                job = JobHeader.objects.get(id=bjo_id)
                shift = Shift.objects.get(id=shift_id)
                operator = Operator.objects.get(id=operator_id)
                
                # Update data
                pipe.bjo = job
                pipe.station = station
                pipe.shift = shift
                pipe.operator = operator
                pipe.save()
                
                messages.success(request, f'Data PIPE untuk BJO {pipe.bjo.bjo} berhasil diupdate!')
                return redirect('pipe_phosphate_summary')
            else:
                messages.error(request, 'Semua field harus diisi!')
                return redirect('pipe_phosphate_edit', header_id=header_id)
            
        except Exception as e:
            messages.error(request, f'Error saat update data: {str(e)}')
            return redirect('pipe_phosphate_edit', header_id=header_id)
    
    # GET request - tampilkan form
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIPE")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PipePhosphateHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()
    
    context = {
        'pipe': pipe,
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
        'active_menu': 'pipe_phosphate_summary',
    }
    
    return render(request, 'pipe/pipe_phosphate_edit.html', context)

@phosphate_access_required
def pipe_phosphate_delete(request, header_id):
    """
    View untuk delete PIPE Protector Phosphated
    """
    pipe = get_object_or_404(PipePhosphateHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_name = pipe.bjo.bjo
            
            # Delete related PipePhosphateDetail first (if any) - sesuaikan dengan nama field relasi
            PipePhosphateDetail.objects.filter(pipephosphate_header=pipe).delete()
            
            # Delete the header
            pipe.delete()
            
            messages.success(request, f'Data PIPE untuk BJO {bjo_name} berhasil dihapus!')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
    
    return redirect('pipe_phosphate_summary')

@phosphate_access_required
def pipe_phosphate_summary_detail(request, header_id):
    from django.db.models import Prefetch
    
    header = get_object_or_404(
        PipePhosphateHeader.objects
        .select_related('bjo', 'operator', 'shift'),
        pk=header_id
    )

    # Group details by joint_number to avoid duplicates
    details_raw = header.pipephosphate_details.select_related('joint_number').all()
    
    # Create a dictionary to group by joint_number
    details_grouped = {}
    for detail in details_raw:
        joint_id = detail.joint_number.id
        if joint_id not in details_grouped:
            details_grouped[joint_id] = {
                'joint_number': detail.joint_number,
                'box_phosphated': False,
                'pin_phosphated': False,
                'created_at': detail.created_at,
                'pipe_details': detail.joint_number.pipedetail_set.all()
            }
        
        # Update phosphate status
        if detail.side_phosphate == 'BOX':
            details_grouped[joint_id]['box_phosphated'] = detail.box_phosphated
        elif detail.side_phosphate == 'PIN':
            details_grouped[joint_id]['pin_phosphated'] = detail.pin_phosphated

    context = {
        'active_menu': 'pipe_phosphate_summary',
        'header': header,
        'details': list(details_grouped.values())
    }
    return render(request, 'pipe/pipe_phosphate_summary_detail.html', context)

@phosphate_access_required
# proses install Protektor ke Pipa
def protector_install_header(request):
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIPE")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PinHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')

        if bjo_id and station and shift_id and operator_id:
            job = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)

            new_header = PipeHeader.objects.create(
                bjo=job,
                station=station,
                shift=shift,
                operator=operator
            )

            return redirect('protector_install_detail', header_id=new_header.id)

    context = {
        'active_menu': 'protector_install',
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
    }

    return render(request, 'install_protector/header.html', context)

@phosphate_access_required
def protector_install_detail(request, header_id):
    """
    View untuk menampilkan detail dan menambahkan joint baru.
    Jika job composite (header.bjo.is_composite=True), BOX & PIN protector tidak wajib diisi.
    """
    header = get_object_or_404(PipeHeader, id=header_id)

    # Cek apakah job ini composite
    is_composite = header.bjo.is_composite

    # Ambil joint yang belum selesai (minimal salah satu sisi belum dipasang)
    pipe_list = SerialNumber.objects.filter(
        Q(is_box_phosphated=True) | Q(is_pin_phosphated=True),
        Q(is_bp_installed=False) | models.Q(is_pp_installed=False),
        bjo=header.bjo
    )

    box_list = BoxDetail.objects.filter(
        is_phosphated=True,
        is_installed=False,
        protector_number__isnull=False
    ).select_related('protector_number')

    pin_list = PinDetail.objects.filter(
        is_phosphated=True,
        is_installed=False,
        protector_number__isnull=False
    ).select_related('protector_number')

    if request.method == 'POST':
        joint_id = request.POST.get('joint_number')
        box_id = request.POST.get('box_side_installed')
        pin_id = request.POST.get('pin_side_installed')
        tally_raw = request.POST.get('tally')

        # Validasi input dasar
        if not joint_id:
            messages.error(request, "Joint Number harus dipilih.")
            return redirect('protector_install_detail', header_id=header.id)

        # Untuk job NON-composite: minimal satu protector wajib diisi
        # Untuk job composite: protector boleh kosong, cukup joint number & tally
        if not is_composite and not box_id and not pin_id:
            messages.error(request, "Minimal salah satu protector (BOX atau PIN) harus dipilih.")
            return redirect('protector_install_detail', header_id=header.id)

        # Validasi tally
        tally = None
        if tally_raw:
            try:
                tally = Decimal(tally_raw)
                if tally <= 0:
                    messages.error(request, "Tally harus berupa angka positif.")
                    return redirect('protector_install_detail', header_id=header.id)
            except InvalidOperation:
                messages.error(request, "Tally harus berupa angka desimal yang valid.")
                return redirect('protector_install_detail', header_id=header.id)

        # Ambil objek dari database
        joint = SerialNumber.objects.filter(id=joint_id).first()
        box = BoxDetail.objects.filter(id=box_id).first() if box_id else None
        pin = PinDetail.objects.filter(id=pin_id).first() if pin_id else None

        if not joint:
            messages.error(request, "Joint Number tidak ditemukan.")
            return redirect('protector_install_detail', header_id=header.id)

        # Validasi status joint
        if box and joint.is_bp_installed:
            messages.error(request, f"BOX protector sudah terpasang pada joint {joint.joint_number}.")
            return redirect('protector_install_detail', header_id=header.id)

        if pin and joint.is_pp_installed:
            messages.error(request, f"PIN protector sudah terpasang pada joint {joint.joint_number}.")
            return redirect('protector_install_detail', header_id=header.id)

        # Validasi protector availability
        if box and box.is_installed:
            messages.error(request, f"BOX protector {box.protector_number} sudah digunakan.")
            return redirect('protector_install_detail', header_id=header.id)

        if pin and pin.is_installed:
            messages.error(request, f"PIN protector {pin.protector_number} sudah digunakan.")
            return redirect('protector_install_detail', header_id=header.id)

        # Cek apakah sudah ada PipeDetail untuk joint ini
        existing_detail = PipeDetail.objects.filter(
            pipe_header=header,
            joint_number=joint
        ).first()

        if existing_detail:
            messages.warning(request, f"Joint {joint.joint_number} sudah ada. Gunakan tombol Action untuk melengkapi protector yang belum terpasang.")
            return redirect('protector_install_detail', header_id=header.id)

        try:
            with transaction.atomic():
                new_detail = PipeDetail.objects.create(
                    pipe_header=header,
                    joint_number=joint,
                    box_protector=box,
                    pin_protector=pin,
                    tally=tally,
                    box_installed_by=header.operator.name if box else None,
                    pin_installed_by=header.operator.name if pin else None,
                )

                # Buat pesan sukses
                installed_items = []
                if box:
                    installed_items.append(f"BOX protector {box.protector_number}")
                if pin:
                    installed_items.append(f"PIN protector {pin.protector_number}")

                completion_status = "dan telah COMPLETE" if new_detail.is_completed else "namun masih INCOMPLETE"

                if is_composite and not installed_items:
                    messages.success(request, f"Berhasil menyimpan joint {joint.joint_number} (Composite) {completion_status}.")
                else:
                    messages.success(request, f"Berhasil memasang {' dan '.join(installed_items)} pada joint {joint.joint_number} {completion_status}.")

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat menyimpan data: {str(e)}")
            return redirect('protector_install_detail', header_id=header.id)

        return redirect('protector_install_detail', header_id=header.id)

    completed_joints = PipeDetail.objects.filter(pipe_header=header).order_by('id')

    context = {
        'active_menu': 'protector_install',
        'header': header,
        'pipe_list': pipe_list,
        'box_list': box_list,
        'pin_list': pin_list,
        'completed_joints': completed_joints,
        'is_composite': is_composite,
    }
    return render(request, 'install_protector/detail.html', context)

@phosphate_access_required
def protector_install_detail_delete(request, detail_id):
    """
    Delete protector install detail and revert all related status
    """
    detail = get_object_or_404(PipeDetail, id=detail_id)
    header_id = detail.pipe_header.id
    joint = detail.joint_number

    joint_number = joint.joint_number
    items_reverted = []

    try:
        with transaction.atomic():
            # Revert BOX protector status jika ada
            if detail.box_protector:
                box_detail = detail.box_protector
                box_detail.is_installed = False
                box_detail.installed_to = None
                box_detail.save()

                joint.is_bp_installed = False
                items_reverted.append(f"BOX ({box_detail.protector_number.serial_number})")

            # Revert PIN protector status jika ada
            if detail.pin_protector:
                pin_detail = detail.pin_protector
                pin_detail.is_installed = False
                pin_detail.installed_to = None
                pin_detail.save()

                joint.is_pp_installed = False
                items_reverted.append(f"PIN ({pin_detail.protector_number.serial_number})")

            # Revert tally info
            if detail.tally:
                items_reverted.append(f"Tally ({detail.tally} inch)")

            joint.save()
            detail.delete()

            items_text = ", ".join(items_reverted) if items_reverted else "No data"
            messages.success(request, f"Data joint {joint_number} ({items_text}) berhasil dihapus dan semua status dikembalikan.")

    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus data: {str(e)}")

    return redirect('protector_install_detail', header_id=header_id)

@phosphate_access_required
def protector_install_update(request, header_id, detail_id):
    """
    View untuk update protector yang belum terpasang pada joint yang sudah ada.
    Untuk job composite, field BOX dan PIN protector bersifat opsional.
    """
    if request.method != 'POST':
        return redirect('protector_install_detail', header_id=header_id)

    header = get_object_or_404(PipeHeader, id=header_id)
    detail = get_object_or_404(PipeDetail, id=detail_id, pipe_header=header)

    # Cek apakah job ini composite
    is_composite = header.bjo.is_composite

    box_id = request.POST.get('box_side_installed')
    pin_id = request.POST.get('pin_side_installed')
    tally_raw = request.POST.get('tally')

    # Validasi: minimal ada yang diupdate
    if not box_id and not pin_id and not tally_raw:
        messages.error(request, "Tidak ada data yang diupdate.")
        return redirect('protector_install_detail', header_id=header.id)

    joint = detail.joint_number

    box = BoxDetail.objects.filter(id=box_id).first() if box_id else None
    pin = PinDetail.objects.filter(id=pin_id).first() if pin_id else None

    # Validasi BOX protector
    if box:
        if detail.box_protector:
            messages.error(request, f"BOX protector sudah terpasang pada joint {joint.joint_number}.")
            return redirect('protector_install_detail', header_id=header.id)

        if box.is_installed:
            messages.error(request, f"BOX protector {box.protector_number} sudah digunakan.")
            return redirect('protector_install_detail', header_id=header.id)

    # Validasi PIN protector
    if pin:
        if detail.pin_protector:
            messages.error(request, f"PIN protector sudah terpasang pada joint {joint.joint_number}.")
            return redirect('protector_install_detail', header_id=header.id)

        if pin.is_installed:
            messages.error(request, f"PIN protector {pin.protector_number} sudah digunakan.")
            return redirect('protector_install_detail', header_id=header.id)

    # Validasi tally
    tally = None
    if tally_raw:
        try:
            tally = Decimal(tally_raw)
            if tally <= 0:
                messages.error(request, "Tally harus berupa angka positif.")
                return redirect('protector_install_detail', header_id=header.id)
        except InvalidOperation:
            messages.error(request, "Tally harus berupa angka desimal yang valid.")
            return redirect('protector_install_detail', header_id=header.id)

    try:
        with transaction.atomic():
            updated_items = []

            if box:
                detail.box_protector = box
                detail.box_installed_by = header.operator.name
                updated_items.append(f"BOX protector {box.protector_number}")

            if pin:
                detail.pin_protector = pin
                detail.pin_installed_by = header.operator.name
                updated_items.append(f"PIN protector {pin.protector_number}")

            if tally is not None:
                detail.tally = tally
                updated_items.append(f"Tally {tally} inch")

            # Save akan trigger logic otomatis di model (termasuk set is_completed)
            detail.save()

            # Buat pesan status completion
            if detail.is_completed:
                completion_status = " Status: COMPLETE ✓"
            else:
                missing_items = []
                # Untuk composite, BOX dan PIN tidak wajib — hanya tally yang dicek
                if not is_composite:
                    if not detail.box_protector:
                        missing_items.append("BOX")
                    if not detail.pin_protector:
                        missing_items.append("PIN")
                if not detail.tally:
                    missing_items.append("Tally")
                completion_status = f" Status: INCOMPLETE (masih perlu: {', '.join(missing_items)})" if missing_items else " Status: COMPLETE ✓"

            messages.success(request, f"Berhasil update {', '.join(updated_items)} pada joint {joint.joint_number}.{completion_status}")

    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat update data: {str(e)}")
        return redirect('protector_install_detail', header_id=header.id)

    return redirect('protector_install_detail', header_id=header.id)

@phosphate_access_required
def protector_install_report(request, header_id):
    selected_header = get_object_or_404(
        PipeHeader.objects
        .select_related('operator', 'shift')
        .prefetch_related('pipe_details__joint_number', 'pipe_details__box_protector', 'pipe_details__pin_protector'),
        id=header_id
    )

    merged_details = defaultdict(lambda: {
        'joint_number': None,
        'box': '',
        'box_installed_by': '',
        'pin': '',
        'pin_installed_by': ''
    })

    for detail in selected_header.pipe_details.all():
        key = detail.joint_number.joint_number
        merged_details[key]['joint_number'] = detail.joint_number
        merged_details[key]['box'] = str(detail.box_protector) if detail.box_protector else ''
        merged_details[key]['box_installed_by'] = detail.box_installed_by or ''
        merged_details[key]['pin'] = str(detail.pin_protector) if detail.pin_protector else ''
        merged_details[key]['pin_installed_by'] = detail.pin_installed_by or ''

    combined_details = list(merged_details.values())

    context = {
        'active_menu': 'protector_install',
        'selected_header': selected_header,
        'combined_details': combined_details,
    }
    return render(request, 'install_protector/report.html', context)

@phosphate_access_required
def protector_install_summary(request):
    """
    View untuk menampilkan summary/list data Install Protector dengan jumlah detail
    """
    from django.db.models import Count, Q, Sum, Case, When, IntegerField, Value
    
    # Ambil parameter filter dengan validasi
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_station = request.GET.get('station', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    # Query dasar dengan annotate untuk hitung detail
    all_pipe = PipeHeader.objects.select_related('bjo', 'operator', 'shift').annotate(
        total_joints=Count('pipe_details', distinct=True),
        box_installed=Sum(
            Case(
                When(pipe_details__box_protector__isnull=False, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        pin_installed=Sum(
            Case(
                When(pipe_details__pin_protector__isnull=False, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    ).all()

    # Filter pencarian (hanya jika query tidak kosong)
    if query:
        all_pipe = all_pipe.filter(
            Q(bjo__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    # Filter BJO (hanya jika tidak kosong)
    if filter_bjo:
        try:
            all_pipe = all_pipe.filter(bjo__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter Station (hanya jika tidak kosong)
    if filter_station:
        all_pipe = all_pipe.filter(station=filter_station)

    # Filter Shift (hanya jika tidak kosong)
    if filter_shift:
        try:
            all_pipe = all_pipe.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tahun
    if filter_year:
        try:
            all_pipe = all_pipe.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan bulan (membutuhkan tahun juga)
    if filter_month and filter_year:
        try:
            all_pipe = all_pipe.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_pipe = all_pipe.filter(created_at__date=date_obj)
        except ValueError:
            pass  # Ignore invalid date format

    all_pipe = all_pipe.order_by('-id')

    # Pagination
    paginator = Paginator(all_pipe, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opsi untuk dropdown dengan error handling
    try:
        bjo_options = PipeHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    try:
        station_options = PipeHeader.objects.filter(
            station__isnull=False
        ).exclude(
            station=''
        ).values_list('station', flat=True).distinct().order_by('station')
    except Exception:
        station_options = []
    
    try:
        # Ambil shift options dengan ID dan nama
        shift_options = PipeHeader.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    # Opsi tahun berdasarkan data yang ada
    try:
        year_options = PipeHeader.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    # Opsi bulan (1-12)
    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_pipe': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_station': filter_station,
        'filter_shift': filter_shift,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'bjo_options': bjo_options,
        'station_options': station_options,
        'shift_options': shift_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'protector_install_summary',
    }

    return render(request, 'install_protector/summary.html', context)

@phosphate_access_required
def protector_install_summary_edit(request, header_id):
    """
    View untuk edit Install Protector dari halaman summary
    """
    pipe = get_object_or_404(PipeHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            # Ambil data dari form
            bjo_id = request.POST.get('bjo')
            station = request.POST.get('station')
            shift_id = request.POST.get('shift')
            operator_id = request.POST.get('operator')
            
            # Validasi data
            if bjo_id and station and shift_id and operator_id:
                job = JobHeader.objects.get(id=bjo_id)
                shift = Shift.objects.get(id=shift_id)
                operator = Operator.objects.get(id=operator_id)
                
                # Update data
                pipe.bjo = job
                pipe.station = station
                pipe.shift = shift
                pipe.operator = operator
                pipe.save()
                
                messages.success(request, f'Data Install Protector untuk BJO {pipe.bjo.bjo} berhasil diupdate!')
                return redirect('protector_install_summary')
            else:
                messages.error(request, 'Semua field harus diisi!')
                return redirect('protector_install_summary_edit', header_id=header_id)
            
        except Exception as e:
            messages.error(request, f'Error saat update data: {str(e)}')
            return redirect('protector_install_summary_edit', header_id=header_id)
    
    # GET request - tampilkan form
    job_list = JobHeader.objects.filter(is_finish=False, bjo_for="PIPE")
    operator_list = Operator.objects.all()
    station_list = [choice[0] for choice in PipeHeader._meta.get_field('station').choices]
    shift_list = Shift.objects.all()
    
    context = {
        'pipe': pipe,
        'job_list': job_list,
        'operator_list': operator_list,
        'station_list': station_list,
        'shift_list': shift_list,
        'active_menu': 'protector_install_summary',
    }
    
    return render(request, 'install_protector/edit.html', context)

@phosphate_access_required
def protector_install_summary_delete(request, header_id):
    """
    View untuk delete Install Protector dari halaman summary
    """
    pipe = get_object_or_404(PipeHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_name = pipe.bjo.bjo
            
            # Delete related PipeDetail first
            PipeDetail.objects.filter(pipe_header=pipe).delete()
            
            # Delete the header
            pipe.delete()
            
            messages.success(request, f'Data Install Protector untuk BJO {bjo_name} berhasil dihapus!')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
    
    return redirect('protector_install_summary')

@phosphate_access_required
def protector_install_summary_detail(request, header_id):
    """
    View untuk menampilkan detail Install Protector dari halaman summary
    """
    pipe_header = get_object_or_404(PipeHeader, id=header_id)
    
    # Ambil semua detail yang terkait dengan header ini
    pipe_details = PipeDetail.objects.filter(
        pipe_header=pipe_header
    ).select_related(
        'joint_number',
        'box_protector',
        'pin_protector'
    ).order_by('-id')
    
    context = {
        'pipe_header': pipe_header,
        'pipe_details': pipe_details,
        'active_menu': 'protector_install_summary',
    }
    
    return render(request, 'install_protector/summary_detail.html', context)

@phosphate_access_required
def protector_install_summary_detail(request, header_id):
    header = get_object_or_404(
        PipeHeader.objects
        .select_related('bjo', 'operator', 'shift'),
        pk=header_id
    )
    
    details = header.pipe_details.select_related(
        'joint_number', 
        'box_protector__protector_number',
        'pin_protector__protector_number'
    ).all()

    context = {
        'active_menu': 'protector_install_summary',
        'header': header,
        'details': details
    }
    return render(request, 'install_protector/summary_detail.html', context)

@phosphate_access_required
def protector_joint_tracking(request):
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_status = request.GET.get('status', '').strip()
    
    results = []
    
    if query or filter_bjo or filter_status:
        # Query PipeDetail untuk tracking
        tracking_query = PipeDetail.objects.select_related(
            'pipe_header', 
            'pipe_header__bjo', 
            'pipe_header__operator',
            'pipe_header__shift',
            'joint_number',
            'box_protector',
            'box_protector__protector_number',
            'pin_protector',
            'pin_protector__protector_number'
        ).all()
        
        # Filter by search query (joint number)
        if query:
            tracking_query = tracking_query.filter(
                joint_number__joint_number__icontains=query
            )
        
        # Filter by BJO
        if filter_bjo:
            tracking_query = tracking_query.filter(
                pipe_header__bjo__bjo=filter_bjo
            )
        
        # Filter by status
        if filter_status == 'completed':
            tracking_query = tracking_query.filter(is_completed=True)
        elif filter_status == 'incomplete':
            tracking_query = tracking_query.filter(is_completed=False)
        
        # Convert to list and apply natural sorting by joint number
        results = list(tracking_query)
        
        def natural_sort_key(item):
            """Extract numeric part from joint number for natural sorting"""
            joint = item.joint_number.joint_number if item.joint_number else ''
            # Extract numbers from string (e.g., "867699" -> 867699, "J 12345" -> 12345)
            numbers = re.findall(r'\d+', joint)
            return int(numbers[0]) if numbers else 0
        
        # Sort by natural order of joint numbers
        results.sort(key=natural_sort_key)
        
        # Pagination
        paginator = Paginator(results, 500)
        page_number = request.GET.get('page')
        results = paginator.get_page(page_number)
    
    # Get filter options
    try:
        bjo_options = PipeHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    context = {
        'results': results,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_status': filter_status,
        'bjo_options': bjo_options,
        'active_menu': 'protector_joint_tracking',
    }
    
    return render(request, 'install_protector/tracking.html', context)

@phosphate_access_required
def box_protector_tracking(request):
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_status = request.GET.get('status', '').strip()
    
    results = []
    
    if query or filter_bjo or filter_status:
        # Query BoxDetail untuk tracking
        tracking_query = BoxDetail.objects.select_related(
            'box_header',
            'box_header__bjo',
            'box_header__operator',
            'box_header__shift',
            'protector_number',
            'installed_to',  # installed_to adalah SerialNumber (joint_number)
        ).prefetch_related(
            'pipedetail_set',  # Untuk mendapatkan PipeDetail yang menggunakan BoxDetail ini
            'pipedetail_set__pipe_header',
        ).all()
        
        # Filter by search query (BOX protector serial number)
        if query:
            tracking_query = tracking_query.filter(
                protector_number__serial_number__icontains=query
            )
        
        # Filter by BJO
        if filter_bjo:
            tracking_query = tracking_query.filter(
                box_header__bjo__bjo=filter_bjo
            )
        
        # Filter by status
        if filter_status == 'installed':
            tracking_query = tracking_query.filter(is_installed=True)
        elif filter_status == 'not_installed':
            tracking_query = tracking_query.filter(is_installed=False)
        
        # Convert to list and apply natural sorting by BP serial number
        results = list(tracking_query)
        
        def natural_sort_key(item):
            """Extract numeric part from serial number for natural sorting"""
            serial = item.protector_number.serial_number if item.protector_number else ''
            # Extract numbers from string (e.g., "H 029" -> 29, "H 095" -> 95)
            numbers = re.findall(r'\d+', serial)
            return int(numbers[0]) if numbers else 0
        
        # Sort by natural order of serial numbers
        results.sort(key=natural_sort_key)
        
        # Pagination
        paginator = Paginator(results, 500)
        page_number = request.GET.get('page')
        results = paginator.get_page(page_number)
    
    # Get filter options
    try:
        bjo_options = BoxHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    context = {
        'results': results,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_status': filter_status,
        'bjo_options': bjo_options,
        'active_menu': 'box_protector_tracking',
    }
    
    return render(request, 'box/tracking.html', context)

@phosphate_access_required
def pin_protector_tracking(request):
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_status = request.GET.get('status', '').strip()
    
    results = []
    
    if query or filter_bjo or filter_status:
        # Query PinDetail untuk tracking
        tracking_query = PinDetail.objects.select_related(
            'pin_header',
            'pin_header__bjo',
            'pin_header__operator',
            'pin_header__shift',
            'protector_number',
            'installed_to',  # installed_to adalah SerialNumber (joint_number)
        ).prefetch_related(
            'pipedetail_set',  # Untuk mendapatkan PipeDetail yang menggunakan PinDetail ini
            'pipedetail_set__pipe_header',
        ).all()
        
        # Filter by search query (PIN protector serial number)
        if query:
            tracking_query = tracking_query.filter(
                protector_number__serial_number__icontains=query
            )
        
        # Filter by BJO
        if filter_bjo:
            tracking_query = tracking_query.filter(
                pin_header__bjo__bjo=filter_bjo
            )
        
        # Filter by status
        if filter_status == 'installed':
            tracking_query = tracking_query.filter(is_installed=True)
        elif filter_status == 'not_installed':
            tracking_query = tracking_query.filter(is_installed=False)
        
        # Convert to list and apply natural sorting by PIN serial number
        results = list(tracking_query)
        
        def natural_sort_key(item):
            """Extract numeric part from serial number for natural sorting"""
            serial = item.protector_number.serial_number if item.protector_number else ''
            # Extract numbers from string (e.g., "P 029" -> 29, "P 095" -> 95)
            numbers = re.findall(r'\d+', serial)
            return int(numbers[0]) if numbers else 0
        
        # Sort by natural order of serial numbers
        results.sort(key=natural_sort_key)
        
        # Pagination
        paginator = Paginator(results, 500)
        page_number = request.GET.get('page')
        results = paginator.get_page(page_number)
    
    # Get filter options
    try:
        bjo_options = PinHeader.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    context = {
        'results': results,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_status': filter_status,
        'bjo_options': bjo_options,
        'active_menu': 'pin_protector_tracking',
    }
    
    return render(request, 'pin/tracking.html', context)

@phosphate_access_required
def report_box_protector(request):
    return render(request, 'report/report_box_protector.html', {'active_menu':'report_box_phosphate'})