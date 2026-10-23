from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Count, Sum, Case, When, IntegerField, Value
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from collections import defaultdict
from production.models import JobHeader, SerialNumber, Operator, Shift
from .models import weldfinal_header, weldfinal_detail
from functools import wraps

def weldfinal_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        allowed_roles = ['operator', 'supervisor', 'admin', 'management', 'leadman']
        
        if request.user.role not in allowed_roles:
            messages.error(request, "You don't have permission to access Weld Final Module. Only Operator, Supervisor, Leadman, Admin, and Management can access this page.")
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper

@weldfinal_access_required
def weldfinal_header_view(request):
    """
    View untuk membuat header weld final
    """
    job_list = JobHeader.objects.filter(bjo_for="PIPE")  # Hanya filter PIPE
    operator_list = Operator.objects.all()
    shift_list = Shift.objects.all()

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')

        if bjo_id and shift_id and operator_id:
            job = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)

            # Simpan ke model weldfinal_header
            new_header = weldfinal_header.objects.create(
                bjo=job,
                shift=shift,
                operator=operator
            )

            return redirect('weldfinal_detail', header_id=new_header.id)

    context = {
        'active_menu': 'weldfinal',
        'job_list': job_list,
        'operator_list': operator_list,
        'shift_list': shift_list,
    }

    return render(request, 'weldfinal/header.html', context)

@weldfinal_access_required
def weldfinal_detail_view(request, header_id):
    """
    View untuk menampilkan detail dan menambahkan joint baru
    """
    header = get_object_or_404(weldfinal_header, id=header_id)

    # Joint yang sudah masuk ke weld final
    existing_joints = weldfinal_detail.objects.filter(
        weldfinal_header=header
    ).values_list('joint_number_id', flat=True)

    # Ambil semua joint dari BJO, kecuali yang sudah diinput
    joint_list = SerialNumber.objects.filter(
        bjo=header.bjo
    ).exclude(id__in=existing_joints).order_by('joint_number')

    if request.method == 'POST':
        joint_id = request.POST.get('joint_number')
        tally_raw = request.POST.get('tally')
        bevel_pin = request.POST.get('bevel_pin') == 'on'
        bevel_box = request.POST.get('bevel_box') == 'on'
        grind_pin = request.POST.get('grind_pin') == 'on'
        grind_box = request.POST.get('grind_box') == 'on'

        # Validasi input dasar
        if not joint_id:
            messages.error(request, "Joint Number harus dipilih.")
            return redirect('weldfinal_detail', header_id=header.id)

        # Validasi tally
        tally = None
        if tally_raw:
            try:
                tally = Decimal(tally_raw)
                if tally <= 0:
                    messages.error(request, "Tally harus berupa angka positif.")
                    return redirect('weldfinal_detail', header_id=header.id)
            except InvalidOperation:
                messages.error(request, "Tally harus berupa angka desimal yang valid.")
                return redirect('weldfinal_detail', header_id=header.id)

        # Ambil objek joint
        joint = SerialNumber.objects.filter(id=joint_id).first()

        if not joint:
            messages.error(request, "Joint Number tidak ditemukan.")
            return redirect('weldfinal_detail', header_id=header.id)

        # Cek apakah joint sudah ada di detail
        existing_detail = weldfinal_detail.objects.filter(
            weldfinal_header=header,
            joint_number=joint
        ).first()

        if existing_detail:
            messages.warning(request, f"Joint {joint.joint_number} sudah ada. Gunakan tombol Action untuk update.")
            return redirect('weldfinal_detail', header_id=header.id)

        try:
            with transaction.atomic():
                # Create new record
                new_detail = weldfinal_detail.objects.create(
                    weldfinal_header=header,
                    joint_number=joint,
                    tally=tally,
                    bevel_pin=bevel_pin,
                    bevel_box=bevel_box,
                    grind_pin=grind_pin,
                    grind_box=grind_box,
                )

                messages.success(request, f"Berhasil menambahkan joint {joint.joint_number}.")

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat menyimpan data: {str(e)}")
            return redirect('weldfinal_detail', header_id=header.id)

        return redirect('weldfinal_detail', header_id=header.id)

    # Ambil detail yang sudah ada
    completed_joints = weldfinal_detail.objects.filter(
        weldfinal_header=header
    ).select_related('joint_number').order_by('id')

    context = {
        'active_menu': 'weldfinal',
        'header': header,
        'joint_list': joint_list,
        'completed_joints': completed_joints,
    }
    return render(request, 'weldfinal/detail.html', context)


@weldfinal_access_required
def weldfinal_detail_delete(request, detail_id):
    """
    Delete weld final detail
    """
    detail = get_object_or_404(weldfinal_detail, id=detail_id)
    header_id = detail.weldfinal_header.id
    joint_number = detail.joint_number.joint_number
    
    try:
        with transaction.atomic():
            # Delete detail
            detail.delete()
            
            messages.success(request, f"Data joint {joint_number} berhasil dihapus.")
            
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus data: {str(e)}")
    
    return redirect('weldfinal_detail', header_id=header_id)


@weldfinal_access_required
def weldfinal_update(request, header_id, detail_id):
    """
    View untuk update weld final detail
    """
    if request.method != 'POST':
        return redirect('weldfinal_detail', header_id=header_id)
    
    header = get_object_or_404(weldfinal_header, id=header_id)
    detail = get_object_or_404(weldfinal_detail, id=detail_id, weldfinal_header=header)
    
    tally_raw = request.POST.get('tally')
    bevel_pin = request.POST.get('bevel_pin') == 'on'
    bevel_box = request.POST.get('bevel_box') == 'on'
    grind_pin = request.POST.get('grind_pin') == 'on'
    grind_box = request.POST.get('grind_box') == 'on'
    
    # Validasi tally
    tally = None
    if tally_raw:
        try:
            tally = Decimal(tally_raw)
            if tally <= 0:
                messages.error(request, "Tally harus berupa angka positif.")
                return redirect('weldfinal_detail', header_id=header.id)
        except InvalidOperation:
            messages.error(request, "Tally harus berupa angka desimal yang valid.")
            return redirect('weldfinal_detail', header_id=header.id)
    
    try:
        with transaction.atomic():
            # Update detail
            if tally is not None:
                detail.tally = tally
            
            detail.bevel_pin = bevel_pin
            detail.bevel_box = bevel_box
            detail.grind_pin = grind_pin
            detail.grind_box = grind_box
            
            detail.save()
            
            messages.success(request, f"Berhasil update joint {detail.joint_number.joint_number}.")
    
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat update data: {str(e)}")
        return redirect('weldfinal_detail', header_id=header.id)
    
    return redirect('weldfinal_detail', header_id=header.id)


@weldfinal_access_required
def weldfinal_report(request, header_id):
    """
    View untuk menampilkan report weld final
    """
    selected_header = get_object_or_404(
        weldfinal_header.objects
        .select_related('operator', 'shift', 'bjo')
        .prefetch_related('weldfinal_details__joint_number'),
        id=header_id
    )

    details = selected_header.weldfinal_details.all()

    context = {
        'active_menu': 'weldfinal',
        'selected_header': selected_header,
        'details': details,
    }
    return render(request, 'weldfinal/report.html', context)


@weldfinal_access_required
def weldfinal_summary(request):
    """
    View untuk menampilkan summary/list data weld final
    """
    from django.db.models import Count
    
    # Ambil parameter filter
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    # Query dasar dengan annotate
    all_weldfinal = weldfinal_header.objects.select_related('bjo', 'operator', 'shift').annotate(
        total_joints=Count('weldfinal_details', distinct=True)
    ).all()

    # Filter pencarian
    if query:
        all_weldfinal = all_weldfinal.filter(
            Q(bjo__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    # Filter BJO
    if filter_bjo:
        try:
            all_weldfinal = all_weldfinal.filter(bjo__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass

    # Filter Shift
    if filter_shift:
        try:
            all_weldfinal = all_weldfinal.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass

    # Filter berdasarkan tahun
    if filter_year:
        try:
            all_weldfinal = all_weldfinal.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass

    # Filter berdasarkan bulan
    if filter_month and filter_year:
        try:
            all_weldfinal = all_weldfinal.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_weldfinal = all_weldfinal.filter(created_at__date=date_obj)
        except ValueError:
            pass

    all_weldfinal = all_weldfinal.order_by('-id')

    # Pagination
    paginator = Paginator(all_weldfinal, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opsi untuk dropdown
    try:
        bjo_options = weldfinal_header.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    try:
        shift_options = weldfinal_header.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    # Opsi tahun
    try:
        year_options = weldfinal_header.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    # Opsi bulan
    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_weldfinal': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_shift': filter_shift,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'bjo_options': bjo_options,
        'shift_options': shift_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'weldfinal_summary',
    }

    return render(request, 'weldfinal/summary.html', context)


@weldfinal_access_required
def weldfinal_summary_edit(request, header_id):
    """
    View untuk edit weld final header dari halaman summary
    """
    weldfinal = get_object_or_404(weldfinal_header, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_id = request.POST.get('bjo')
            shift_id = request.POST.get('shift')
            operator_id = request.POST.get('operator')
            
            if bjo_id and shift_id and operator_id:
                job = JobHeader.objects.get(id=bjo_id)
                shift = Shift.objects.get(id=shift_id)
                operator = Operator.objects.get(id=operator_id)
                
                weldfinal.bjo = job
                weldfinal.shift = shift
                weldfinal.operator = operator
                weldfinal.save()
                
                messages.success(request, f'Data Weld Final untuk BJO {weldfinal.bjo.bjo} berhasil diupdate!')
                return redirect('weldfinal_summary')
            else:
                messages.error(request, 'Semua field harus diisi!')
                return redirect('weldfinal_summary_edit', header_id=header_id)
            
        except Exception as e:
            messages.error(request, f'Error saat update data: {str(e)}')
            return redirect('weldfinal_summary_edit', header_id=header_id)
    
    # GET request
    job_list = JobHeader.objects.filter(bjo_for="PIPE")  # Hanya filter PIPE
    operator_list = Operator.objects.all()
    shift_list = Shift.objects.all()
    
    context = {
        'weldfinal': weldfinal,
        'job_list': job_list,
        'operator_list': operator_list,
        'shift_list': shift_list,
        'active_menu': 'weldfinal_summary',
    }
    
    return render(request, 'weldfinal/edit.html', context)


@weldfinal_access_required
def weldfinal_summary_delete(request, header_id):
    """
    View untuk delete weld final dari halaman summary
    """
    weldfinal = get_object_or_404(weldfinal_header, id=header_id)
    
    if request.method == 'POST':
        try:
            bjo_name = weldfinal.bjo.bjo
            
            # Delete related details first
            weldfinal_detail.objects.filter(weldfinal_header=weldfinal).delete()
            
            # Delete the header
            weldfinal.delete()
            
            messages.success(request, f'Data Weld Final untuk BJO {bjo_name} berhasil dihapus!')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
    
    return redirect('weldfinal_summary')


@weldfinal_access_required
def weldfinal_summary_detail(request, header_id):
    """
    View untuk menampilkan detail weld final dari halaman summary
    """
    weldfinal_hdr = get_object_or_404(weldfinal_header, id=header_id)
    
    # Ambil semua detail
    weldfinal_dtl = weldfinal_detail.objects.filter(
        weldfinal_header=weldfinal_hdr
    ).select_related('joint_number').order_by('-id')
    
    context = {
        'weldfinal_header': weldfinal_hdr,
        'weldfinal_details': weldfinal_dtl,
        'active_menu': 'weldfinal_summary',
    }

    return render(request, 'weldfinal/summary_detail.html', context)

@weldfinal_access_required
def weldfinal_joint_tracking(request):
    """
    View untuk tracking joint di weld final
    """
    import re
    
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    
    results = []
    
    if query or filter_bjo:
        # Query weldfinal_detail untuk tracking
        tracking_query = weldfinal_detail.objects.select_related(
            'weldfinal_header', 
            'weldfinal_header__bjo', 
            'weldfinal_header__operator',
            'weldfinal_header__shift',
            'joint_number'
        ).all()
        
        # Filter by search query (joint number)
        if query:
            tracking_query = tracking_query.filter(
                joint_number__joint_number__icontains=query
            )
        
        # Filter by BJO
        if filter_bjo:
            tracking_query = tracking_query.filter(
                weldfinal_header__bjo__bjo=filter_bjo
            )
        
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
        bjo_options = weldfinal_header.objects.filter(
            bjo__isnull=False
        ).values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')
    except Exception:
        bjo_options = []
    
    context = {
        'results': results,
        'query': query,
        'filter_bjo': filter_bjo,
        'bjo_options': bjo_options,
        'active_menu': 'weldfinal_tracking',
    }
    
    return render(request, 'weldfinal/tracking.html', context)

@weldfinal_access_required
def index(request):
    """
    Dashboard Weld Final - Menampilkan BJO yang sudah selesai dan on progress
    """
    
    # Ambil semua BJO yang memiliki record weld final
    # PERBAIKAN: Gunakan 'weldfinal_header' bukan 'weldfinal_detail'
    weldfinal_bjos = JobHeader.objects.filter(
        weldfinal_header__isnull=False
    ).distinct()
    
    # BJO yang sudah selesai
    finished_bjos = []
    for bjo in weldfinal_bjos:
        # Hitung total yang sudah selesai (semua proses complete)
        total_finished = weldfinal_detail.objects.filter(
            weldfinal_header__bjo=bjo,
            tally__gt=0,
            bevel_pin=True,
            bevel_box=True,
            grind_pin=True,
            grind_box=True
        ).count()
        
        if bjo.qty and total_finished >= bjo.qty and total_finished > 0:
            finished_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_finished': total_finished,
                'finish_date': weldfinal_detail.objects.filter(
                    weldfinal_header__bjo=bjo
                ).order_by('-created_at').first().created_at.date() if weldfinal_detail.objects.filter(weldfinal_header__bjo=bjo).exists() else None
            })
    
    # BJO yang sedang on progress
    progress_bjos = []
    for bjo in weldfinal_bjos:
        # Hitung total yang sudah selesai
        total_finished = weldfinal_detail.objects.filter(
            weldfinal_header__bjo=bjo,
            tally__gt=0,
            bevel_pin=True,
            bevel_box=True,
            grind_pin=True,
            grind_box=True
        ).count()
        
        if bjo.qty and 0 < total_finished < bjo.qty:
            remaining = bjo.qty - total_finished
            progress_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_finished': total_finished,
                'remaining_qty': remaining
            })
    
    # Summary statistics
    stats = {
        'total_finished': len(finished_bjos),
        'total_progress': len(progress_bjos),
    }
    
    # Ambil 5 terakhir untuk setiap kategori
    finished_bjos_last5 = sorted(finished_bjos, key=lambda x: x['finish_date'] or date.min, reverse=True)[:5]
    progress_bjos_last5 = progress_bjos[:5]
    
    context = {
        'finished_bjos': finished_bjos_last5,
        'progress_bjos': progress_bjos_last5,
        'stats': stats,
        'active_menu': 'weldfinal',
    }
    
    return render(request, 'weldfinal/index.html', context)