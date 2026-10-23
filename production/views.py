from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from .models import *
from django.utils.timezone import now
from datetime import datetime as dt, date, timedelta
from .services import calculate_custom_oee
from django.db.models import Q, Sum, Value, F, Count, Case, When
from django.core.paginator import Paginator
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.templatetags.static import static
from decimal import Decimal, InvalidOperation
from django.db.models.functions import Concat
from django.urls import reverse
from django.db import transaction
import json
from django.utils import timezone
from phosphate.models import PipeDetail
from django.views.decorators.http import require_GET
from cutting.models import cut_header, cut_detail
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from collections import defaultdict
from django.http import HttpResponseForbidden
from functools import wraps
from .decorators import *
from weldfinal.models import *

def get_machines_by_process(request):
    process_type_id = request.GET.get('process_type')
    machines = Machine.objects.filter(process_type_id=process_type_id)
    data = [{'id': m.id, 'name': m.name} for m in machines]
    return JsonResponse(data, safe=False)

def index(request):
    # BJO Threading yang sudah selesai (5 terakhir)
    thread_finished = JobHeader.objects.filter(
        process_type__name='THREADING',
        is_finish=True
    ).order_by('-finish_date')[:5]
    
    # BJO Welding yang sudah selesai (5 terakhir)
    weld_finished = JobHeader.objects.filter(
        process_type__name='WELDING',
        is_finish=True
    ).order_by('-finish_date')[:5]
    
    # BJO Threading yang sedang on progress (5 terakhir)
    thread_progress = JobHeader.objects.filter(
        process_type__name='THREADING',
        is_finish=False
    ).order_by('-start_date')[:5]
    
    # BJO Welding yang sedang on progress (5 terakhir)
    weld_progress = JobHeader.objects.filter(
        process_type__name='WELDING',
        is_finish=False
    ).order_by('-start_date')[:5]
    
    # Summary statistics
    stats = {
        'thread_total_finished': JobHeader.objects.filter(
            process_type__name='THREADING', 
            is_finish=True
        ).count(),
        'weld_total_finished': JobHeader.objects.filter(
            process_type__name='WELDING', 
            is_finish=True
        ).count(),
        'thread_total_progress': JobHeader.objects.filter(
            process_type__name='THREADING', 
            is_finish=False
        ).count(),
        'weld_total_progress': JobHeader.objects.filter(
            process_type__name='WELDING', 
            is_finish=False
        ).count(),
    }
    
    context = {
        'thread_finished': thread_finished,
        'weld_finished': weld_finished,
        'thread_progress': thread_progress,
        'weld_progress': weld_progress,
        'stats': stats,
    }
    
    return render(request, 'production/index.html', context)

def job_list(request):
    jobs = JobHeader.objects.all()
    return render(request, 'job/list.html', {'jobs': jobs})

def job_add(request):
    pass

def calculate_apq(header_instance):
    """
    Hitung Availability, Performance, Quality (APQ)
    sesuai logika di service.py
    """
    from .services import calculate_availability, calculate_performance, calculate_quality
    from .models import CycleTime

    # Cek apakah Thread atau Weld
    is_thread = header_instance.__class__.__name__ == 'ThreadHeader'

    # Ambil job detail
    if is_thread:
        job_detail = header_instance.threaddetail_set.first()
    else:
        job_detail = header_instance.welddetail_set.first()

    if not job_detail:
        return Decimal('0'), Decimal('0'), Decimal('0')

    job = job_detail.bjo
    cycle_time_obj = CycleTime.objects.filter(
        process_type=job.process_type,
        od_thickness=job.size,
        ct_for=job.ct_reference
    ).first()

    actual_output = header_instance.actual_output or Decimal('0')
    actual_hours = header_instance.actual_hours or Decimal('0')
    booked_hours = header_instance.booked_hours.duration if header_instance.booked_hours else Decimal('0')
    standard_cycle_time = cycle_time_obj.hours if cycle_time_obj and cycle_time_obj.hours else Decimal('0')

    if booked_hours == 0 or standard_cycle_time == 0:
        return Decimal('0'), Decimal('0'), Decimal('0')

    availability = calculate_availability(header_instance, booked_hours, is_thread)
    performance = calculate_performance(actual_output, actual_hours or booked_hours, standard_cycle_time)
    quality = calculate_quality(header_instance, actual_output, is_thread)

    return availability, performance, quality


def oee_weekly_report(request):
    current_week = datetime.now().isocalendar()[1]
    today = now().date()

    # Ambil data H+1 (exclude hari ini)
    thread_headers = ThreadHeader.objects.filter(
        date__week=current_week,
        date__lt=today,
        is_posted=True
    )
    weld_headers = WeldHeader.objects.filter(
        date__week=current_week,
        date__lt=today,
        is_posted=True
    )

    all_headers = list(thread_headers) + list(weld_headers)

    report_data = []
    for h in all_headers:
        availability, performance, quality = calculate_apq(h)
        oee_decimal = availability * performance * quality
        oee_percentage = round(oee_decimal * 100, 2)

        report_data.append({
            "date": h.date,
            "machine": h.machine.name if h.machine else "-",
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee_decimal": oee_decimal,
            "oee_percentage": oee_percentage
        })

    return render(request, "reports/oee_weekly.html", {"report": report_data})

def oee_dashboard(request):
    today = now().date()

    # Batas waktu
    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    month_start = today.replace(day=1)
    quarter = (today.month - 1) // 3 + 1
    quarter_months = range((quarter - 1) * 3 + 1, quarter * 3 + 1)
    year_start = today.replace(month=1, day=1)

    # Fungsi ambil data dengan filter H+1
    def get_headers(model, date_filter):
        return model.objects.filter(
            date__range=date_filter,
            date__lt=today,
            is_posted=True
        )

    def get_monthly_headers(model):
        return model.objects.filter(
            date__month=today.month,
            date__year=today.year,
            date__lt=today,
            is_posted=True
        )

    def get_quarterly_headers(model):
        return model.objects.filter(
            date__month__in=quarter_months,
            date__year=today.year,
            date__lt=today,
            is_posted=True
        )

    def get_yearly_headers(model):
        return model.objects.filter(
            date__year=today.year,
            date__lt=today,
            is_posted=True
        )

    # Build laporan OEE lengkap
    def build_oee_report(querysets):
        all_data = []
        for qs in querysets:
            for p in qs:
                availability, performance, quality = calculate_apq(p)
                oee_decimal = availability * performance * quality
                oee_percentage = round(oee_decimal * 100, 2)

                all_data.append({
                    "date": p.date,
                    "machine": p.machine.name if p.machine else "-",
                    "shift": p.shift.name if p.shift else "-",
                    "operator": p.operator.name if p.operator else "-",
                    "availability": availability,
                    "performance": performance,
                    "quality": quality,
                    "oee_decimal": oee_decimal,
                    "oee_percentage": oee_percentage
                })
        return all_data

    context = {
        "weekly_report": build_oee_report([
            get_headers(ThreadHeader, (start_week, end_week)),
            get_headers(WeldHeader, (start_week, end_week))
        ]),
        "monthly_report": build_oee_report([
            get_monthly_headers(ThreadHeader),
            get_monthly_headers(WeldHeader)
        ]),
        "quarterly_report": build_oee_report([
            get_quarterly_headers(ThreadHeader),
            get_quarterly_headers(WeldHeader)
        ]),
        "yearly_report": build_oee_report([
            get_yearly_headers(ThreadHeader),
            get_yearly_headers(WeldHeader)
        ]),
    }

    return render(request, "reports/oee_dashboard.html", context)

def daily_production_report(request, header_type, header_id):
    """
    header_type: 'thread' atau 'weld'
    """
    if header_type == "thread":
        header = get_object_or_404(ThreadHeader, id=header_id)
        details = header.threaddetail_set.select_related('bjo').order_by('bjo__bjo', 'joint_number')
    elif header_type == "weld":
        header = get_object_or_404(WeldHeader, id=header_id)
        details = header.welddetail_set.select_related('bjo').order_by('bjo__bjo', 'conn_number')
    else:
        raise ValueError("Invalid header type")

    return render(request, 'reports/daily_report.html', {
        'header': header,
        'details': details,
    })
    
def clean_conn_number(conn_number):
    if not conn_number:
        return ''
    cleaned = conn_number.replace(' ', '')
    cleaned = cleaned.strip().upper()
    
    return cleaned

@joborder_write_access_required   
def joborder_header(request):
    if request.method == 'POST':
        if not request.POST.get('bjo') or not request.POST.get('qty'):
            messages.error(request, "BJO dan Qty wajib diisi.")
        else:
            bjo = request.POST.get('bjo')
            
            # Validasi duplikasi BJO
            if JobHeader.objects.filter(bjo=bjo).exists():
                messages.error(request, f"BJO '{bjo}' sudah ada. Silakan gunakan BJO yang berbeda.")
            else:
                try:
                    qty = float(request.POST.get('qty'))
                    if qty < 0:
                        messages.error(request, "Qty tidak boleh negatif.")
                    else:
                        # Handle empty date fields
                        start_date = request.POST.get('start_date')
                        end_date = request.POST.get('end_date')
                        
                        # Convert empty strings to None for date fields
                        if start_date == '':
                            start_date = None
                        if end_date == '':
                            end_date = None
                            
                        # Handle foreign key fields (convert empty strings to None)
                        size_id = request.POST.get('size') or None
                        conn_id = request.POST.get('conn') or None
                        info_id = request.POST.get('info') or None
                        ct_reference_id = request.POST.get('ct_reference') or None
                        process_type_id = request.POST.get('process_type') or None

                        JobHeader.objects.create(
                            bjo=bjo,
                            bt=request.POST.get('bt'),
                            customer=request.POST.get('customer'),
                            qty=qty,
                            product=request.POST.get('product'),
                            bjo_for=request.POST.get('bjo_for'),
                            lube=request.POST.get('lube'),
                            type_order=request.POST.get('type_order'),
                            size_id=size_id,
                            conn_id=conn_id,
                            info_id=info_id,
                            ct_reference_id=ct_reference_id,
                            process_type_id=process_type_id,
                            start_date=start_date,
                            end_date=end_date,
                            is_finish=False,
                            finish_date=None,
                            is_composite=request.POST.get('is_composite') == 'on',  # TAMBAHAN
                        )
                        messages.success(request, "Job Order berhasil disimpan.")
                        return redirect('joborder_list')
                except ValueError:
                    messages.error(request, "Qty harus berupa angka.")
                except Exception as e:
                    messages.error(request, f"Terjadi kesalahan: {str(e)}")

    process_size_mapping = {}
    process_list = Process.objects.all()
    
    for process in process_list:
        sizes = OdThickness.objects.filter(process_type=process).order_by('size')
        process_size_mapping[str(process.id)] = [
            {'id': size.id, 'name': str(size)} 
            for size in sizes
        ]

    context = {
        'size_list': OdThickness.objects.all(),
        'conn_list': Connection.objects.all(),
        'info_list': InfoTag.objects.all(),
        'grade_list': MaterialGrade.objects.all(),
        'process_list': process_list,
        'process_size_mapping': json.dumps(process_size_mapping),
        'bjo_for_choices': JobHeader._meta.get_field('bjo_for').choices,
        'type_order_choices': JobHeader._meta.get_field('type_order').choices,
        'active_menu': 'joborder_list',
    }
    return render(request, 'joborder/header.html', context)

def update_job_status(header):
    """
    Function untuk mengupdate status job berdasarkan total finished
    """
    # Hitung total finished dari semua detail
    total_finished = jobDetail.objects.filter(job=header).aggregate(
        total=Sum('finished')
    )['total'] or 0
    
    # Update status berdasarkan apakah total finished >= qty
    if header.qty is not None and total_finished >= header.qty:
        if not header.is_finish:  # Hanya update jika belum finish
            header.is_finish = True
            header.finish_date = date.today()  # Set tanggal hari ini
            header.save()
    else:
        if header.is_finish:  # Jika sebelumnya finish tapi sekarang kurang
            header.is_finish = False
            header.finish_date = None
            header.save()
            
def parse_decimal(value, field_name, required=False, allow_negative=False):
    if not value or value.strip() == '':
        if required:
            raise ValueError(f"Field '{field_name}' wajib diisi.")
        return Decimal(0)
    
    try:
        parsed_value = Decimal(str(value).strip())
        
        # Validasi nilai negatif hanya jika tidak diizinkan
        if not allow_negative and parsed_value < 0:
            raise ValueError(f"Field '{field_name}' tidak boleh negatif.")
        
        return parsed_value
        
    except (InvalidOperation, TypeError):
        raise ValueError(f"Field '{field_name}' harus berupa angka yang valid.")
    
@joborder_access_required
def joborder_detail(request, header_id):
    header = get_object_or_404(JobHeader, pk=header_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'edit':
            return handle_edit_joborder_detail(request, header_id)

        # Handle Add New Detail
        try:
            # Parse and validate input values
            box = parse_decimal(request.POST.get('box'), 'Box')
            pin = parse_decimal(request.POST.get('pin'), 'Pin')
            fs = parse_decimal(request.POST.get('fs'), 'FS')
            fc = parse_decimal(request.POST.get('fc'), 'FC')
            finished = parse_decimal(request.POST.get('finished'), 'Finished', required=True, allow_negative=True)
            
            if finished is None:
                messages.error(request, "Field 'Finished' wajib diisi.")
                return redirect('joborder_detail', header_id=header.id)

            remarks = request.POST.get('remarks', '').strip()
            if remarks and len(remarks) > 100:
                messages.error(request, "Remarks maksimal 100 karakter.")
                return redirect('joborder_detail', header_id=header.id)

            # Hitung total finished yang sudah ada
            existing_total = jobDetail.objects.filter(job=header).aggregate(
                total=Sum('finished')
            )['total'] or Decimal(0)
            
            # Peringatan jika job sudah completed
            if header.is_finish:
                messages.warning(
                    request,
                    "Perhatian: Job Order sudah completed. Menambah data dapat mengubah status job."
                )
            with transaction.atomic():
                jobDetail.objects.create(
                    job=header,
                    box=box,
                    pin=pin,
                    fs=fs,
                    fc=fc,
                    finished=finished,
                    remarks=remarks if remarks else None,
                )
                
                # Update status job header
                update_job_status(header)
            
            # Cek apakah total finished (termasuk yang baru) melebihi qty - hanya warning
            new_total = existing_total + finished
            if header.qty is not None:
                if new_total > header.qty:
                    remaining = header.qty - existing_total
                    messages.warning(
                        request,
                        f"Data berhasil disimpan, tetapi perhatian: "
                        f"Jumlah 'Finished' total ({new_total}) melebihi Qty di Job Header ({header.qty}). "
                        f"Sisa qty sebelumnya: {remaining}."
                    )
                elif finished < 0:
                    messages.info(
                        request,
                        f"Job detail dengan adjustment negatif ({finished}) berhasil ditambahkan. "
                        f"Total finished sekarang: {new_total}"
                    )
                else:
                    messages.success(request, "Job detail berhasil ditambahkan.")
            else:
                messages.success(request, "Job detail berhasil ditambahkan.")
            
            return redirect('joborder_detail', header_id=header.id)

        except ValueError as e:
            messages.error(request, str(e))
            return redirect('joborder_detail', header_id=header.id)
        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('joborder_detail', header_id=header.id)

    # Get detail list and calculations
    detail_list = jobDetail.objects.filter(job=header).order_by('-created_at', '-id')
    
    # Hitung remaining quantity
    total_finished = detail_list.aggregate(total=Sum('finished'))['total'] or Decimal(0)
    remaining_qty = header.qty - total_finished if header.qty else Decimal(0)

    return render(request, 'joborder/detail.html', {
        'header': header,
        'detail_list': detail_list,
        'remaining_qty': remaining_qty,
        'total_finished': total_finished,
        'active_menu': 'joborder_list',
    })

@joborder_write_access_required
def handle_edit_joborder_detail(request, header_id):
    """Handle edit job detail"""
    header = get_object_or_404(JobHeader, pk=header_id)
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('joborder_detail', header_id=header.id)
    
    try:
        detail = jobDetail.objects.get(id=detail_id, job=header)
    except jobDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('joborder_detail', header_id=header.id)
    
    try:
        # Parse and validate input values
        box = parse_decimal(request.POST.get('box'), 'Box')
        pin = parse_decimal(request.POST.get('pin'), 'Pin')
        fs = parse_decimal(request.POST.get('fs'), 'FS')
        fc = parse_decimal(request.POST.get('fc'), 'FC')
        # Finished boleh negatif untuk adjustment/koreksi
        finished = parse_decimal(request.POST.get('finished'), 'Finished', required=True, allow_negative=True)
        
        if finished is None:
            messages.error(request, "Field 'Finished' wajib diisi.")
            return redirect('joborder_detail', header_id=header.id)

        # PERBAIKAN: Hapus validasi finished <= 0 karena boleh negatif untuk adjustment

        remarks = request.POST.get('remarks', '').strip()
        if remarks and len(remarks) > 100:
            messages.error(request, "Remarks maksimal 100 karakter.")
            return redirect('joborder_detail', header_id=header.id)

        # Hitung total finished yang sudah ada (kecuali detail yang sedang diedit)
        existing_total = jobDetail.objects.filter(job=header).exclude(id=detail_id).aggregate(
            total=Sum('finished')
        )['total'] or Decimal(0)
        
        # Peringatan jika job sudah completed
        if header.is_finish:
            messages.warning(
                request,
                "Perhatian: Job Order sudah completed. Mengubah data dapat mempengaruhi status job."
            )
        
        # PERBAIKAN: Update data SELALU, tapi beri warning jika melebihi qty
        with transaction.atomic():
            detail.box = box
            detail.pin = pin
            detail.fs = fs
            detail.fc = fc
            detail.finished = finished
            detail.remarks = remarks if remarks else None
            detail.save()
            
            # Update status job header
            update_job_status(header)
        
        # Cek apakah total finished (termasuk yang baru) melebihi qty - hanya warning
        new_total = existing_total + finished
        if header.qty is not None:
            if new_total > header.qty:
                remaining = header.qty - existing_total
                messages.warning(
                    request,
                    f"Data berhasil diupdate, tetapi perhatian: "
                    f"Jumlah 'Finished' total ({new_total}) melebihi Qty di Job Header ({header.qty}). "
                    f"Sisa qty sebelumnya: {remaining}."
                )
            elif finished < 0:
                # Informasi tambahan jika edit dengan nilai negatif (adjustment)
                messages.info(
                    request,
                    f"Job detail dengan adjustment negatif ({finished}) berhasil diupdate. "
                    f"Total finished sekarang: {new_total}"
                )
            else:
                messages.success(request, "Job detail berhasil diupdate.")
        else:
            messages.success(request, "Job detail berhasil diupdate.")
        
        return redirect('joborder_detail', header_id=header.id)
        
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('joborder_detail', header_id=header.id)
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('joborder_detail', header_id=header.id)
    
@joborder_delete_access_required
def joborder_detail_delete(request, header_id):
    """Delete job detail"""
    header = get_object_or_404(JobHeader, pk=header_id)
    
    if request.method != 'POST':
        messages.error(request, "Method tidak diizinkan.")
        return redirect('joborder_detail', header_id=header.id)
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('joborder_detail', header_id=header.id)
    
    try:
        detail = jobDetail.objects.get(id=detail_id, job=header)
        
        # Simpan info untuk pesan konfirmasi
        finished_qty = detail.finished
        
        # Peringatan jika job sudah completed
        if header.is_finish:
            messages.warning(
                request,
                f"Perhatian: Job Order sudah completed. Menghapus detail dapat mempengaruhi status job."
            )
        
        # Hapus detail dengan transaction untuk konsistensi data
        with transaction.atomic():
            detail.delete()
            
            # Update status job header setelah penghapusan
            update_job_status(header)
        
        messages.success(request, f"Detail job dengan finished qty {finished_qty} berhasil dihapus.")
        return redirect('joborder_detail', header_id=header.id)
        
    except jobDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('joborder_detail', header_id=header.id)
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus: {str(e)}")
        return redirect('joborder_detail', header_id=header.id)

def get_filter_options(request):
    """
    AJAX endpoint untuk mendapatkan BJO dan BT options berdasarkan process
    """
    process_id = request.GET.get('process', '')
    
    filtered_base = JobHeader.objects.all()
    
    if process_id:
        filtered_base = filtered_base.filter(process_type__id=process_id)
    
    # Get BJO options
    bjo_options = list(filtered_base.values_list('bjo', flat=True).distinct().order_by('bjo'))
    
    # Get BT options
    bt_options = list(filtered_base.exclude(bt__isnull=True).exclude(bt='').values_list('bt', flat=True).distinct().order_by('bt'))
    
    return JsonResponse({
        'bjo_options': bjo_options,
        'bt_options': bt_options
    })

@joborder_access_required
def joborder_list(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    filter_bt = request.GET.get('bt', '')
    filter_process = request.GET.get('process', '')
    filter_year = request.GET.get('year', '')
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    headers = JobHeader.objects.all()

    # Filter Process Type PERTAMA (untuk cascading effect)
    if filter_process:
        headers = headers.filter(process_type__id=filter_process)

    # Filter pencarian
    if query:
        headers = headers.filter(
            Q(bjo__icontains=query) |
            Q(customer__icontains=query) |
            Q(product__icontains=query)
        )

    # Filter BJO
    if filter_bjo:
        headers = headers.filter(bjo=filter_bjo)

    # Filter BT
    if filter_bt:
        headers = headers.filter(bt=filter_bt)

    # Filter berdasarkan tahun
    if filter_year:
        headers = headers.filter(start_date__year=filter_year)

    # Filter berdasarkan bulan (membutuhkan tahun juga)
    if filter_month and filter_year:
        headers = headers.filter(
            start_date__year=filter_year,
            start_date__month=filter_month
        )

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(start_date=date_obj)
        except ValueError:
            pass

    # Filter berdasarkan status selesai
    if filter_status == 'completed':
        headers = headers.filter(is_finish=True)
    elif filter_status == 'in_progress':
        headers = headers.filter(is_finish=False)

    headers = headers.order_by('-id')

    # Handle filter berdasarkan remaining_qty (manual filtering)
    if filter_status in ['completed_by_qty', 'progress_by_qty', 'zero_qty']:
        headers_list = list(headers)
        if filter_status == 'completed_by_qty':
            headers_list = [h for h in headers_list if h.remaining_qty == 0]
        elif filter_status == 'progress_by_qty':
            headers_list = [h for h in headers_list if h.remaining_qty > 0]
        elif filter_status == 'zero_qty':
            headers_list = [h for h in headers_list if h.qty == 0]

        paginator = Paginator(headers_list, 10)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
    else:
        paginator = Paginator(headers, 10)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

    # Opsi Process Type untuk dropdown (semua unique process dari model Process)
    from .models import Process
    all_process_options = Process.objects.all().order_by('name')

    # Opsi yang sudah difilter berdasarkan process_type (untuk cascading)
    filtered_base = JobHeader.objects.all()
    if filter_process:
        filtered_base = filtered_base.filter(process_type__id=filter_process)

    # BJO options (difilter berdasarkan process jika ada)
    bjo_options = filtered_base.values_list('bjo', flat=True).distinct().order_by('bjo')
    
    # BT options (difilter berdasarkan process jika ada)
    bt_options = filtered_base.exclude(bt__isnull=True).exclude(bt='').values_list('bt', flat=True).distinct().order_by('bt')
    
    # Year options (difilter berdasarkan process jika ada)
    year_options = filtered_base.dates('start_date', 'year').values_list('start_date__year', flat=True).distinct()

    # Opsi bulan (1-12)
    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'headers': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_bt': filter_bt,
        'filter_process': filter_process,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'filter_status': filter_status,
        'bjo_options': bjo_options,
        'bt_options': bt_options,
        'process_options': all_process_options,
        'year_options': year_options,
        'month_options': month_options,
        'active_menu': 'joborder_list',
    }

    return render(request, 'joborder/list.html', context)

@joborder_pdf_access_required
def joborder_pdf(request):
    # Ambil semua parameter filter dari request
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    filter_bt = request.GET.get('bt', '')  # DITAMBAHKAN: filter BT yang hilang
    filter_year = request.GET.get('year', '')
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    jobs = JobHeader.objects.all().order_by('bt', 'id')

    # Terapkan filter yang sama seperti di joborder_list
    if query:
        jobs = jobs.filter(
            Q(bjo__icontains=query) |
            Q(bt__icontains=query) |
            Q(customer__icontains=query) |
            Q(product__icontains=query)
        )

    if filter_bjo:
        jobs = jobs.filter(bjo=filter_bjo)

    # DITAMBAHKAN: Filter berdasarkan BT
    if filter_bt:
        jobs = jobs.filter(bt=filter_bt)

    # Filter berdasarkan tahun
    if filter_year:
        jobs = jobs.filter(start_date__year=filter_year)

    # Filter berdasarkan bulan (membutuhkan tahun juga)
    if filter_month and filter_year:
        jobs = jobs.filter(
            start_date__year=filter_year,
            start_date__month=filter_month
        )

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            jobs = jobs.filter(start_date=date_obj)
        except ValueError:
            pass  # Ignore invalid date format

    # Filter berdasarkan status selesai
    if filter_status == 'completed':
        jobs = jobs.filter(is_finish=True)
    elif filter_status == 'in_progress':
        jobs = jobs.filter(is_finish=False)

    # Handle filter berdasarkan remaining_qty (manual filtering)
    if filter_status in ['completed_by_qty', 'progress_by_qty']:
        jobs_list = list(jobs)
        if filter_status == 'completed_by_qty':
            jobs = [j for j in jobs_list if j.remaining_qty == 0]
        elif filter_status == 'progress_by_qty':
            jobs = [j for j in jobs_list if j.remaining_qty > 0]

    today = date.today()

    # Buat informasi filter untuk ditampilkan di PDF
    filter_info = []
    if query:
        filter_info.append(f"Pencarian: {query}")
    if filter_bjo:
        filter_info.append(f"BJO: {filter_bjo}")
    if filter_bt:  # DITAMBAHKAN: Info filter BT
        filter_info.append(f"BT: {filter_bt}")
    if filter_year:
        filter_info.append(f"Tahun: {filter_year}")
    if filter_month:
        month_names = {
            '1': 'Januari', '2': 'Februari', '3': 'Maret', '4': 'April',
            '5': 'Mei', '6': 'Juni', '7': 'Juli', '8': 'Agustus',
            '9': 'September', '10': 'Oktober', '11': 'November', '12': 'Desember'
        }
        filter_info.append(f"Bulan: {month_names.get(filter_month, filter_month)}")
    if filter_date:
        filter_info.append(f"Tanggal: {filter_date}")
    if filter_status:
        status_names = {
            'completed': 'Selesai',
            'in_progress': 'Dalam Progress',
            'completed_by_qty': 'Selesai (berdasarkan qty)',
            'progress_by_qty': 'Progress (berdasarkan qty)'
        }
        filter_info.append(f"Status: {status_names.get(filter_status, filter_status)}")

    template_path = 'joborder/pdf.html'
    context = {
        'jobs': jobs,
        'today': today,
        'filter_info': filter_info,
        'has_filters': bool(query or filter_bjo or filter_bt or filter_year or filter_month or filter_date or filter_status),  # DIPERBAIKI: tambahkan filter_bt
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="job_order_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@joborder_write_access_required
def joborder_edit(request, header_id):
    header = get_object_or_404(JobHeader, pk=header_id)

    if request.method == 'POST':
        bjo = request.POST.get('bjo')
        qty_input = request.POST.get('qty')

        # Validasi wajib isi
        if not bjo or not qty_input:
            messages.error(request, "BJO dan Qty wajib diisi.")
        else:
            # Validasi duplikasi BJO (kecuali untuk record yang sedang diedit)
            if JobHeader.objects.filter(bjo=bjo).exclude(pk=header.pk).exists():
                messages.error(request, f"BJO '{bjo}' sudah ada. Silakan gunakan BJO yang berbeda.")
            else:
                try:
                    qty = float(qty_input)
                    if qty < 0:
                        messages.error(request, "Qty tidak boleh negatif.")
                    else:
                        # Hitung total finished yang sudah ada
                        total_finished = jobDetail.objects.filter(job=header).aggregate(
                            total=Sum('finished')
                        )['total'] or 0

                        # Validasi qty tidak boleh lebih kecil dari total finished
                        if qty < total_finished:
                            messages.error(
                                request,
                                f"Qty tidak boleh kurang dari total finished ({total_finished}). "
                                "Silakan hapus atau edit detail job terlebih dahulu."
                            )
                        else:
                            # Update field
                            header.bjo = bjo
                            header.bt = request.POST.get('bt')
                            header.customer = request.POST.get('customer')
                            header.product = request.POST.get('product')
                            header.qty = qty
                            header.bjo_for = request.POST.get('bjo_for')
                            header.lube = request.POST.get('lube')
                            header.type_order = request.POST.get('type_order')
                            header.size_id = request.POST.get('size') or None
                            header.conn_id = request.POST.get('conn') or None
                            header.info_id = request.POST.get('info') or None
                            header.ct_reference_id = request.POST.get('ct_reference') or None
                            header.process_type_id = request.POST.get('process_type') or None
                            header.is_composite = request.POST.get('is_composite') == 'on'  # TAMBAHAN
                            
                            # Handle date fields
                            start_date = request.POST.get('start_date')
                            end_date = request.POST.get('end_date')
                            header.start_date = start_date if start_date else None
                            header.end_date = end_date if end_date else None

                            header.save()

                            # Update status job otomatis
                            update_job_status(header)

                            messages.success(request, "Job Order berhasil diperbarui.")
                            return redirect('joborder_list')
                except ValueError:
                    messages.error(request, "Qty harus berupa angka.")

    # Hitung data untuk tampilan
    total_finished = jobDetail.objects.filter(job=header).aggregate(
        total=Sum('finished')
    )['total'] or 0
    remaining_qty = (header.qty - total_finished) if header.qty else 0

    context = {
        'header': header,
        'size_list': OdThickness.objects.all(),
        'conn_list': Connection.objects.all(),
        'info_list': InfoTag.objects.all(),
        'grade_list': MaterialGrade.objects.all(),
        'process_list': Process.objects.all(),
        'bjo_for_choices': JobHeader._meta.get_field('bjo_for').choices,
        'type_order_choices': JobHeader._meta.get_field('type_order').choices,
        'total_finished': total_finished,
        'remaining_qty': remaining_qty,
        'active_menu': 'joborder_list',
    }
    return render(request, 'joborder/edit.html', context)

@joborder_delete_access_required
def joborder_delete(request, header_id):
    """
    View untuk menghapus Job Order
    """
    if request.method == 'POST':
        try:
            job_order = get_object_or_404(JobHeader, id=header_id)
            bjo_number = job_order.bjo
            job_order.delete()
            
            messages.success(request, f'Job Order {bjo_number} berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('joborder_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('bjo'):
                query_params.append(f"bjo={request.GET.get('bjo')}")
            if request.GET.get('year'):
                query_params.append(f"year={request.GET.get('year')}")
            if request.GET.get('month'):
                query_params.append(f"month={request.GET.get('month')}")
            if request.GET.get('date'):
                query_params.append(f"date={request.GET.get('date')}")
            if request.GET.get('status'):
                query_params.append(f"status={request.GET.get('status')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Job Order: {str(e)}')
            return redirect('joborder_list')
    
    return redirect('joborder_list')

@jointnumber_access_required
def jointnumber_list(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    per_page = request.GET.get('per_page', '10')
    
    try:
        per_page = int(per_page)
        if per_page not in [10, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    joint_numbers = SerialNumber.objects.select_related('bjo').order_by('-created_at')

    # Apply search filter
    if query:
        joint_numbers = joint_numbers.filter(
            Q(joint_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )
    
    # Apply BJO filter
    if filter_bjo:
        joint_numbers = joint_numbers.filter(bjo__id=filter_bjo)
    
    status_counts = joint_numbers.aggregate(
        box_threaded=Count('id', filter=Q(is_box_threaded=True)),
        pin_threaded=Count('id', filter=Q(is_pin_threaded=True)),
        box_phosphated=Count('id', filter=Q(is_box_phosphated=True)),
        pin_phosphated=Count('id', filter=Q(is_pin_phosphated=True)),
        fs_welded=Count('id', filter=Q(is_fs_welded=True)),
        fcbs_welded=Count('id', filter=Q(is_fcbs_welded=True)),
        fcps_welded=Count('id', filter=Q(is_fcps_welded=True)),
        bp_installed=Count('id', filter=Q(is_bp_installed=True)),
        pp_installed=Count('id', filter=Q(is_pp_installed=True)),
        beveled=Count('id', filter=Q(is_beveled=True)),
        used=Count('id', filter=Q(is_used=True)),
        ncr=Count('id', filter=Q(is_ncr=True)), 
        rwk=Count('id', filter=Q(is_rwk=True)),
    )
    
    # Total data yang sedang ditampilkan (setelah filter)
    total_filtered = joint_numbers.count()

    # Pagination
    paginator = Paginator(joint_numbers, per_page)
    page_number = request.GET.get('page')
    joint_numbers_page = paginator.get_page(page_number)

    # Get all BJO for filter dropdown
    bjo_list = JobHeader.objects.filter(is_finish__in=[False, None]).order_by('bjo')

    context = {
        'joint_numbers': joint_numbers_page,
        'bjo_list': bjo_list,
        'query': query,
        'filter_bjo': filter_bjo,
        'per_page': str(per_page),
        'active_menu': 'jointnumber_list',
        'status_counts': status_counts,
        'total_filtered': total_filtered,
    }
    
    return render(request, 'jointnumber/list.html', context)

def update_joint_welding_status(joint_number, pin_or_box):
    """Update welding status for joint number based on pin_or_box selection"""
    try:
        serial_number = SerialNumber.objects.get(joint_number=joint_number)
        
        # Update welding status based on pin_or_box value
        if pin_or_box == 'FLOAT SHOE':
            serial_number.is_fs_welded = True
        elif pin_or_box == 'FLOAT COLAR BOX SIDE':
            serial_number.is_fcbs_welded = True
        elif pin_or_box == 'FLOAT COLAR PIN SIDE':
            serial_number.is_fcps_welded = True
        
        # Check if all processes are complete to set is_used
        if (serial_number.is_box_threaded and 
            serial_number.is_pin_threaded and 
            serial_number.is_box_phosphated and 
            serial_number.is_pin_phosphated and
            serial_number.is_fs_welded and
            serial_number.is_fcbs_welded and
            serial_number.is_fcps_welded and
            serial_number.is_bp_installed and
            serial_number.is_pp_installed and
            serial_number.is_beveled):
            serial_number.is_used = True
        
        serial_number.save()
        
    except SerialNumber.DoesNotExist:
        # If joint number doesn't exist in SerialNumber, skip
        pass
    except Exception as e:
        # Log the error for debugging
        print(f"Error updating joint welding status: {str(e)}")

@jointnumber_pdf_access_required
def jointnumber_pdf(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')

    joint_numbers = SerialNumber.objects.select_related('bjo').order_by('-created_at')

    if query:
        joint_numbers = joint_numbers.filter(
            Q(joint_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )

    if filter_bjo:
        joint_numbers = joint_numbers.filter(bjo__id=filter_bjo)

    # Get logo
    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))
    today = date.today()

    # Render ke PDF
    template_path = 'jointnumber/pdf.html'
    context = {
        'joint_numbers': joint_numbers,
        'logo_url': logo_url,
        'today': today,
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="laporan_joint_number.pdf"'

    # Render HTML ke PDF
    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@jointnumber_write_access_required
def manual_add_joint_number(request):
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        joint_number = request.POST.get('joint_number', '').strip()

        # Checkbox to boolean
        is_box_threaded = bool(request.POST.get('is_box_threaded'))
        is_pin_threaded = bool(request.POST.get('is_pin_threaded'))
        is_box_phosphated = bool(request.POST.get('is_box_phosphated'))
        is_pin_phosphated = bool(request.POST.get('is_pin_phosphated'))
        is_used = bool(request.POST.get('is_used'))
        is_ncr = bool(request.POST.get('is_ncr'))

        if not bjo_id or not joint_number:
            messages.error(request, "BJO dan Joint Number wajib diisi.")
            return redirect('manual_add_joint_number')

        # Filter hanya untuk BJO PIPE
        bjo = JobHeader.objects.filter(id=bjo_id, bjo_for='PIPE').first()
        if not bjo:
            messages.error(request, "BJO PIPE tidak ditemukan.")
            return redirect('manual_add_joint_number')

        # Cek apakah qty sudah penuh
        existing_count = SerialNumber.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0

        if existing_count >= max_allowed:
            messages.error(request, f"Tidak dapat menambah joint number. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('manual_add_joint_number')

        # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
        existing_serial = SerialNumber.objects.filter(joint_number=joint_number).first()
        if existing_serial:
            messages.error(request, f"Joint Number '{joint_number}' sudah digunakan di BJO {existing_serial.bjo.bjo}. Pilih nomor lain.")
            return redirect('manual_add_joint_number')

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                # Simpan joint number
                SerialNumber.objects.create(
                    bjo=bjo,
                    joint_number=joint_number,
                    is_box_threaded=is_box_threaded,
                    is_pin_threaded=is_pin_threaded,
                    is_box_phosphated=is_box_phosphated,
                    is_pin_phosphated=is_pin_phosphated,
                    is_used=is_used,
                    is_ncr=is_ncr,
                )

                # Hitung informasi untuk pesan
                total_generated = existing_count + 1
                remaining_after = max_allowed - total_generated
                progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
                
                success_msg = f"Joint Number '{joint_number}' berhasil ditambahkan. "
                success_msg += f"Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
                
                # Cek apakah job sudah complete
                if remaining_after == 0:
                    success_msg += " - BJO COMPLETED!"
                    
                messages.success(request, success_msg)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat menambah joint number: {str(e)}")
            return redirect('manual_add_joint_number')

        return redirect('manual_add_joint_number')

    # Hanya tampilkan BJO dengan kategori PIPE
    jobheaders = JobHeader.objects.filter(bjo_for='PIPE')

    # Tambahkan informasi existing count untuk setiap BJO
    for header in jobheaders:
        header.existing_count = SerialNumber.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count
    
    context = {
        'jobheaders': jobheaders,
         'active_menu': 'jointnumber_list',
    }
    return render(request, 'jointnumber/manual_add.html', context)

@jointnumber_write_access_required
def generate_joint_number(request):
    if request.method == 'POST':
        try:
            bjo_id = int(request.POST.get('bjo'))
            start = int(request.POST.get('start_number'))
            end = int(request.POST.get('end_number'))
        except (TypeError, ValueError):
            messages.error(request, "Semua input harus diisi dengan benar.")
            return redirect('generate_joint_number')

        if start > end:
            messages.error(request, "Start Number tidak boleh lebih besar dari End Number.")
            return redirect('generate_joint_number')

        bjo = JobHeader.objects.filter(id=bjo_id, bjo_for='PIPE').first()
        if not bjo:
            messages.error(request, "BJO PIPE tidak ditemukan.")
            return redirect('generate_joint_number')

        # Ambil jumlah serial number yang sudah ada untuk BJO ini
        existing_count = SerialNumber.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0

        # Hitung berapa banyak yang akan dibuat
        requested_count = end - start + 1
        available_slots = max_allowed - existing_count

        if available_slots <= 0:
            messages.error(request, f"Tidak dapat menambah joint number. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('generate_joint_number')

        if requested_count > available_slots:
            messages.warning(request, f"Permintaan {requested_count} joint number melebihi slot yang tersisa ({available_slots}). Akan dibuat sebanyak {available_slots} joint number saja.")

        created_count = 0
        duplicates = []
        created_joints = []

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                for number in range(start, end + 1):
                    # Stop jika sudah mencapai batas maksimal
                    if existing_count + created_count >= max_allowed:
                        break

                    joint = str(number).zfill(3)

                    # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
                    existing_serial = SerialNumber.objects.filter(joint_number=joint).first()
                    if existing_serial:
                        duplicates.append(f"{joint} (sudah ada di BJO {existing_serial.bjo.bjo})")
                        continue

                    SerialNumber.objects.create(
                        bjo=bjo,
                        joint_number=joint,
                        is_box_threaded=False,
                        is_pin_threaded=False,
                        is_box_phosphated=False,
                        is_pin_phosphated=False,
                        is_ncr=False,
                        is_used=False,
                    )
                    created_joints.append(joint)
                    created_count += 1

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat membuat joint number: {str(e)}")
            return redirect('generate_joint_number')

        # Pesan hasil
        if created_count == 0:
            if duplicates:
                messages.warning(request, f"Tidak ada joint number yang dibuat. Semua nomor sudah ada di sistem: {', '.join(duplicates)}")
            else:
                messages.warning(request, "Tidak ada joint number yang dibuat karena jumlah sudah mencapai qty.")
        else:
            # Hitung informasi progress
            total_generated = existing_count + created_count
            remaining_after = max_allowed - total_generated
            progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
            
            success_msg = f"{created_count} joint number berhasil dibuat: {created_joints[0]} - {created_joints[-1]}."
            
            if duplicates:
                success_msg += f" Nomor yang sudah ada di sistem (dilewati): {', '.join(duplicates)}."
            
            # Tambahkan informasi progress
            success_msg += f" Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
            
            # Cek apakah job sudah complete
            if remaining_after == 0:
                success_msg += " - BJO COMPLETED!"
                
            messages.success(request, success_msg)

        return redirect('generate_joint_number')

    # Tambahkan informasi untuk template (hanya PIPE saja)
    jobheaders = JobHeader.objects.filter(bjo_for='PIPE')
    for header in jobheaders:
        header.existing_count = SerialNumber.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count

    context = {
        'jobheaders': jobheaders,
         'active_menu': 'jointnumber_list',
    }
    return render(request, 'jointnumber/generate.html', context)

@jointnumber_delete_access_required
def delete_jointnumber(request, id):
    """
    View untuk menghapus Joint Number
    """
    if request.method == 'POST':
        try:
            joint_number = get_object_or_404(SerialNumber, id=id)
            joint_number_name = joint_number.joint_number
            joint_number.delete()
            
            messages.success(request, f'Joint Number {joint_number_name} berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('jointnumber_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('bjo'):
                query_params.append(f"bjo={request.GET.get('bjo')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Joint Number: {str(e)}')
            return redirect('jointnumber_list')
    
    return redirect('jointnumber_list')

@boxprotector_access_required
def boxprotector_list(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    filter_threaded = request.GET.get('threaded', '')
    filter_beveled = request.GET.get('beveled', '')
    per_page = request.GET.get('per_page', '10')
    
    # Validate per_page parameter
    try:
        per_page = int(per_page)
        if per_page not in [10, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    items = BoxProtector.objects.select_related('bjo').order_by('-created_at')

    # Pencarian (search)
    if query:
        items = items.filter(
            Q(serial_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )

    # Filter BJO
    if filter_bjo:
        items = items.filter(bjo__id=filter_bjo)
    
    items_for_count = items
    
    status_counts = items_for_count.aggregate(
        threaded=Count('id', filter=Q(is_threaded=True)),
        beveled=Count('id', filter=Q(is_beveled=True)),
        phosphated=Count('id', filter=Q(is_used=True)),
        ncr=Count('id', filter=Q(is_ncr=True)),
        rwk=Count('id', filter=Q(is_rwk=True)),
    )
    
    # Filter Threaded (SETELAH hitung status)
    if filter_threaded:
        if filter_threaded == 'true':
            items = items.filter(is_threaded=True)
        elif filter_threaded == 'false':
            items = items.filter(is_threaded=False)
    
    # Filter Beveled (SETELAH hitung status)
    if filter_beveled:
        if filter_beveled == 'true':
            items = items.filter(is_beveled=True)
        elif filter_beveled == 'false':
            items = items.filter(is_beveled=False)
    
    total_filtered = items.count()

    # Pagination
    paginator = Paginator(items, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Filter bjo_list hanya untuk BOX PROTECTOR
    bjo_list = JobHeader.objects.filter(bjo_for='BOX PROTECTOR')

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_threaded': filter_threaded,
        'filter_beveled': filter_beveled,
        'per_page': str(per_page),
        'bjo_list': bjo_list,
        'active_menu': 'boxprotector_list',
        'status_counts': status_counts,
        'total_filtered': total_filtered,
    }
    return render(request, 'boxprotector/list.html', context)

@boxprotector_pdf_access_required
def boxprotector_pdf(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')

    items = BoxProtector.objects.select_related('bjo', 'bjo__process_type', 'bjo__size').order_by('-created_at')

    if query:
        items = items.filter(
            Q(serial_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )
    if filter_bjo:
        items = items.filter(bjo__id=filter_bjo)

    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))

    context = {
        'items': items,
        'logo_url': logo_url,
        'today': date.today(),
        'user': request.user,
        'active_menu': 'boxprotector_list',
    }

    template_path = 'boxprotector/pdf.html'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="box_protector_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@boxprotector_write_access_required
def boxprotector_edit(request, pk):
    item = get_object_or_404(BoxProtector, pk=pk)

    # Jika box protector sudah threaded DAN phosphated, tidak boleh diedit
    if item.is_threaded and item.is_used:
        messages.warning(request, f"Box Protector {item.serial_number} sudah di-threaded dan phosphated, tidak dapat diedit.")
        # Tetap tampilkan halaman edit tapi dalam mode read-only
        
        # Hitung remaining slots untuk display saja
        jobheaders_with_remaining = []
        for jobheader in JobHeader.objects.filter(bjo_for='BOX PROTECTOR'):
            existing_count = BoxProtector.objects.filter(bjo=jobheader).count()
            remaining_slots = jobheader.qty - existing_count
            jobheader.remaining_slots = remaining_slots
            jobheader.existing_count = existing_count
            jobheaders_with_remaining.append(jobheader)

        context = {
            'item': item,
            'jobheaders': jobheaders_with_remaining,
            'active_menu': 'boxprotector_list',
        }
        return render(request, 'boxprotector/edit.html', context)

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        new_bjo = JobHeader.objects.filter(id=bjo_id, bjo_for='BOX PROTECTOR').first()
        if not new_bjo:
            messages.error(request, "BJO BOX PROTECTOR tidak valid.")
            return redirect('boxprotector_list')

        new_serial_number = request.POST.get('serial_number', '').strip()
        
        # Validasi serial number tidak boleh kosong
        if not new_serial_number:
            messages.error(request, "Serial Number tidak boleh kosong.")
            return redirect('boxprotector_edit', pk=pk)

        # Cek duplikat GLOBAL - kecuali serial number yang sedang diedit
        existing_box = BoxProtector.objects.filter(serial_number=new_serial_number).exclude(pk=item.pk).first()
        if existing_box:
            messages.error(request, f"Serial Number {new_serial_number} sudah digunakan di BJO {existing_box.bjo.bjo}. Pilih nomor lain.")
            return redirect('boxprotector_edit', pk=pk)

        # Jika mengganti BJO, cek apakah BJO baru memiliki slot tersisa
        if item.bjo != new_bjo:
            # Hitung slot tersisa untuk BJO baru
            existing_count = BoxProtector.objects.filter(bjo=new_bjo).count()
            remaining_slots = new_bjo.qty - existing_count
            
            if remaining_slots <= 0:
                messages.error(request, f"BJO {new_bjo.bjo} sudah penuh. Tidak dapat memindahkan box protector ke BJO ini.")
                return redirect('boxprotector_edit', pk=pk)

        item.bjo = new_bjo
        item.serial_number = new_serial_number
        # Jangan ubah is_used dari form
        item.save()
        messages.success(request, "Box Protector berhasil diperbarui.")
        return redirect('boxprotector_list')

    # Hitung remaining slots untuk setiap JobHeader
    jobheaders_with_remaining = []
    for jobheader in JobHeader.objects.filter(bjo_for='BOX PROTECTOR'):
        existing_count = BoxProtector.objects.filter(bjo=jobheader).count()
        remaining_slots = jobheader.qty - existing_count
        
        # Jika ini adalah BJO yang sedang digunakan oleh item, tambah 1 ke remaining
        # karena setelah edit, slot dari item ini akan kosong
        if item.bjo == jobheader:
            remaining_slots += 1
            
        jobheader.remaining_slots = remaining_slots
        jobheader.existing_count = existing_count
        jobheaders_with_remaining.append(jobheader)

    context = {
        'item': item,
        'jobheaders': jobheaders_with_remaining,
        'active_menu': 'boxprotector_list',
    }
    return render(request, 'boxprotector/edit.html', context)

@boxprotector_write_access_required
def generate_box_protector_view(request):
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        prefix = request.POST.get('prefix')
        try:
            start = int(request.POST.get('start_number'))
            end = int(request.POST.get('end_number'))
        except (TypeError, ValueError):
            messages.error(request, "Nomor awal dan akhir harus berupa angka.")
            return redirect('generate_box_protector')

        if start > end:
            messages.error(request, "Nomor awal tidak boleh lebih besar dari nomor akhir.")
            return redirect('generate_box_protector')

        if not bjo_id or not prefix:
            messages.error(request, "Semua field wajib diisi.")
            return redirect('generate_box_protector')

        bjo = JobHeader.objects.filter(id=bjo_id).first()
        if not bjo:
            messages.error(request, "BJO tidak ditemukan.")
            return redirect('generate_box_protector')

        # Cek jumlah existing dan batasan qty
        existing_count = BoxProtector.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0
        requested_count = end - start + 1
        available_slots = max_allowed - existing_count

        if available_slots <= 0:
            messages.error(request, f"Tidak dapat menambah box protector. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('generate_box_protector')

        if requested_count > available_slots:
            messages.warning(request, f"Permintaan {requested_count} box protector melebihi slot yang tersisa ({available_slots}). Akan dibuat sebanyak {available_slots} saja.")

        created_count = 0
        duplicates = []
        created_serials = []

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                for i in range(start, end + 1):
                    # Stop jika sudah mencapai batas maksimal
                    if existing_count + created_count >= max_allowed:
                        break

                    serial = f"{prefix}{i:03d}"
                    
                    # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
                    existing_box = BoxProtector.objects.filter(serial_number=serial).first()
                    if existing_box:
                        duplicates.append(f"{serial} (sudah ada di BJO {existing_box.bjo.bjo})")
                        continue

                    BoxProtector.objects.create(
                        bjo=bjo,
                        serial_number=serial,
                        is_used=False
                    )
                    created_serials.append(serial)
                    created_count += 1

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat membuat box protector: {str(e)}")
            return redirect('generate_box_protector')

        # Pesan hasil
        if created_count == 0:
            if duplicates:
                messages.warning(request, f"Tidak ada box protector yang dibuat. Semua serial sudah ada di sistem: {', '.join(duplicates)}")
            else:
                messages.warning(request, "Tidak ada box protector yang dibuat karena jumlah sudah mencapai qty.")
        else:
            # Hitung informasi progress
            total_generated = existing_count + created_count
            remaining_after = max_allowed - total_generated
            progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
            
            success_msg = f"{created_count} BOX serial berhasil dibuat: {created_serials[0]} - {created_serials[-1]}."
            
            if duplicates:
                success_msg += f" Serial yang sudah ada di sistem (dilewati): {', '.join(duplicates)}."
            
            # Tambahkan informasi progress
            success_msg += f" Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
            
            # Cek apakah job sudah complete
            if remaining_after == 0:
                success_msg += " - BJO COMPLETED!"
                
            messages.success(request, success_msg)

        return redirect('generate_box_protector')

    # Tambahkan informasi untuk template
    bjo_list = JobHeader.objects.filter(bjo_for='BOX PROTECTOR')
    for header in bjo_list:
        header.existing_count = BoxProtector.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count

    context = {
        'bjo_list': bjo_list,
        'active_menu': 'boxprotector_list',
    }
    return render(request, 'boxprotector/generate.html', context)

@boxprotector_write_access_required
def manual_add_box_protector(request):
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        serial_number = request.POST.get('serial_number', '').strip()

        if not bjo_id or not serial_number:
            messages.error(request, "BJO dan Serial Number wajib diisi.")
            return redirect('manual_add_box_protector')

        # Cek BJO
        bjo = JobHeader.objects.filter(id=bjo_id).first()
        if not bjo:
            messages.error(request, "BJO tidak ditemukan.")
            return redirect('manual_add_box_protector')

        # Cek apakah qty sudah penuh
        existing_count = BoxProtector.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0

        if existing_count >= max_allowed:
            messages.error(request, f"Tidak dapat menambah box protector. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('manual_add_box_protector')

        # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
        existing_box = BoxProtector.objects.filter(serial_number=serial_number).first()
        if existing_box:
            messages.error(request, f"Serial Number '{serial_number}' sudah digunakan di BJO {existing_box.bjo.bjo}. Pilih nomor lain.")
            return redirect('manual_add_box_protector')

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                # Simpan box protector
                BoxProtector.objects.create(
                    bjo=bjo,
                    serial_number=serial_number,
                    is_used=False
                )

                # Hitung informasi untuk pesan
                total_generated = existing_count + 1
                remaining_after = max_allowed - total_generated
                progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
                
                success_msg = f"Serial Number '{serial_number}' berhasil ditambahkan. "
                success_msg += f"Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
                
                # Cek apakah job sudah complete
                if remaining_after == 0:
                    success_msg += " - BJO COMPLETED!"
                    
                messages.success(request, success_msg)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat menambah box protector: {str(e)}")
            return redirect('manual_add_box_protector')

        return redirect('manual_add_box_protector')

    # Tambahkan informasi existing count untuk setiap BJO
    jobheaders = JobHeader.objects.filter(bjo_for='BOX PROTECTOR')
    for header in jobheaders:
        header.existing_count = BoxProtector.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count

    context = {
        'jobheaders': jobheaders,
        'active_menu': 'boxprotector_list',
    }
    return render(request, 'boxprotector/manual_add.html', context)

@boxprotector_delete_access_required
def delete_boxprotector(request, id):
    """
    View untuk menghapus Box Protector
    """
    if request.method == 'POST':
        try:
            box_protector = get_object_or_404(BoxProtector, id=id)
            serial_number_name = box_protector.serial_number
            box_protector.delete()
            
            messages.success(request, f'Serial Number {serial_number_name} berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('boxprotector_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('bjo'):
                query_params.append(f"bjo={request.GET.get('bjo')}")
            if request.GET.get('threaded'):
                query_params.append(f"threaded={request.GET.get('threaded')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Serial Number: {str(e)}')
            return redirect('boxprotector_list')
    
    return redirect('boxprotector_list')

@jointnumber_write_access_required
def edit_jointnumber(request, pk):
    joint = get_object_or_404(SerialNumber, pk=pk)

    # Jika joint number sudah digunakan, tidak boleh diedit
    if joint.is_used:
        messages.warning(request, f"Joint Number {joint.joint_number} sudah digunakan dan tidak dapat diedit.")
        # Tetap tampilkan halaman edit tapi dalam mode read-only
        
        # Hitung remaining slots untuk display saja
        jobheaders_with_remaining = []
        for jobheader in JobHeader.objects.filter(bjo_for='PIPE'):
            existing_count = SerialNumber.objects.filter(bjo=jobheader).count()
            remaining_slots = jobheader.qty - existing_count
            jobheader.remaining_slots = remaining_slots
            jobheader.existing_count = existing_count
            jobheaders_with_remaining.append(jobheader)

        context = {
            'joint': joint,
            'jobheaders': jobheaders_with_remaining,
            'active_menu': 'jointnumber_list',
        }
        return render(request, 'jointnumber/edit.html', context)

    if request.method == 'POST':
        # Pastikan hanya bisa update ke BJO kategori PIPE
        bjo_id = request.POST.get('bjo')
        new_bjo = JobHeader.objects.filter(id=bjo_id, bjo_for='PIPE').first()
        if not new_bjo:
            messages.error(request, "BJO PIPE tidak valid.")
            return redirect('jointnumber_list')

        new_joint_number = request.POST.get('joint_number', '').strip()
        
        # Validasi joint number tidak boleh kosong
        if not new_joint_number:
            messages.error(request, "Joint Number tidak boleh kosong.")
            return redirect('edit_jointnumber', pk=pk)

        # Cek duplikat GLOBAL - kecuali joint number yang sedang diedit
        existing_joint = SerialNumber.objects.filter(joint_number=new_joint_number).exclude(pk=joint.pk).first()
        if existing_joint:
            messages.error(request, f"Joint Number {new_joint_number} sudah digunakan di BJO {existing_joint.bjo.bjo}. Pilih nomor lain.")
            return redirect('edit_jointnumber', pk=pk)

        # Jika mengganti BJO, cek apakah BJO baru memiliki slot tersisa
        if joint.bjo != new_bjo:
            # Hitung slot tersisa untuk BJO baru
            existing_count = SerialNumber.objects.filter(bjo=new_bjo).count()
            remaining_slots = new_bjo.qty - existing_count
            
            if remaining_slots <= 0:
                messages.error(request, f"BJO {new_bjo.bjo} sudah penuh. Tidak dapat memindahkan joint number ke BJO ini.")
                return redirect('edit_jointnumber', pk=pk)

        joint.bjo = new_bjo
        joint.joint_number = new_joint_number
        # tidak ada update boolean sesuai instruksi
        joint.save()

        messages.success(request, "Joint Number berhasil diupdate.")
        return redirect('jointnumber_list')

    # Hitung remaining slots untuk setiap JobHeader
    jobheaders_with_remaining = []
    for jobheader in JobHeader.objects.filter(bjo_for='PIPE'):
        existing_count = SerialNumber.objects.filter(bjo=jobheader).count()
        remaining_slots = jobheader.qty - existing_count
        
        # Jika ini adalah BJO yang sedang digunakan oleh joint, tambah 1 ke remaining
        # karena setelah edit, slot dari joint ini akan kosong
        if joint.bjo == jobheader:
            remaining_slots += 1
            
        jobheader.remaining_slots = remaining_slots
        jobheader.existing_count = existing_count
        jobheaders_with_remaining.append(jobheader)

    context = {
        'joint': joint,
        'jobheaders': jobheaders_with_remaining,
        'active_menu': 'jointnumber_list',
    }
    return render(request, 'jointnumber/edit.html', context)

@pinprotector_write_access_required
def pinprotector_generate(request):
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        prefix = request.POST.get('prefix')
        
        try:
            start = int(request.POST.get('start_number'))
            end = int(request.POST.get('end_number'))
        except (TypeError, ValueError):
            messages.error(request, "Start Number dan End Number harus berupa angka.")
            return redirect('pinprotector_generate')

        if start > end:
            messages.error(request, "Start Number tidak boleh lebih besar dari End Number.")
            return redirect('pinprotector_generate')

        if not bjo_id or not prefix:
            messages.error(request, "Semua field wajib diisi.")
            return redirect('pinprotector_generate')

        bjo = JobHeader.objects.filter(id=bjo_id).first()
        if not bjo:
            messages.error(request, "BJO tidak ditemukan.")
            return redirect('pinprotector_generate')

        # Cek jumlah existing dan batasan qty
        existing_count = PinProtector.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0
        requested_count = end - start + 1
        available_slots = max_allowed - existing_count

        if available_slots <= 0:
            messages.error(request, f"Tidak dapat menambah pin protector. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('pinprotector_generate')

        if requested_count > available_slots:
            messages.warning(request, f"Permintaan {requested_count} pin protector melebihi slot yang tersisa ({available_slots}). Akan dibuat sebanyak {available_slots} saja.")

        created_count = 0
        duplicates = []
        created_serials = []

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                for i in range(start, end + 1):
                    # Stop jika sudah mencapai batas maksimal
                    if existing_count + created_count >= max_allowed:
                        break

                    serial = f"{prefix}{i:03d}"
                    
                    # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
                    existing_pin = PinProtector.objects.filter(serial_number=serial).first()
                    if existing_pin:
                        duplicates.append(f"{serial} (sudah ada di BJO {existing_pin.bjo.bjo})")
                        continue

                    PinProtector.objects.create(
                        bjo=bjo,
                        serial_number=serial,
                        is_used=False
                    )
                    created_serials.append(serial)
                    created_count += 1

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat membuat pin protector: {str(e)}")
            return redirect('pinprotector_generate')

        # Pesan hasil
        if created_count == 0:
            if duplicates:
                messages.warning(request, f"Tidak ada pin protector yang dibuat. Semua serial sudah ada di sistem: {', '.join(duplicates)}")
            else:
                messages.warning(request, "Tidak ada pin protector yang dibuat karena jumlah sudah mencapai qty.")
        else:
            # Hitung informasi progress
            total_generated = existing_count + created_count
            remaining_after = max_allowed - total_generated
            progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
            
            success_msg = f"{created_count} PIN serial numbers berhasil dibuat: {created_serials[0]} - {created_serials[-1]}."
            
            if duplicates:
                success_msg += f" Serial yang sudah ada di sistem (dilewati): {', '.join(duplicates)}."
            
            # Tambahkan informasi progress
            success_msg += f" Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
            
            # Cek apakah job sudah complete
            if remaining_after == 0:
                success_msg += " - BJO COMPLETED!"
                
            messages.success(request, success_msg)

        return redirect('pinprotector_generate')

    # Tambahkan informasi untuk template
    jobheaders = JobHeader.objects.filter(bjo_for='PIN PROTECTOR')
    for header in jobheaders:
        header.existing_count = PinProtector.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count
        
    context = {
        'jobheaders': jobheaders,
        'active_menu': 'pinprotector_list',
    }

    return render(request, 'pinprotector/generate.html', context)

@pinprotector_write_access_required
def manual_add_pin_protector(request):
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        serial_number = request.POST.get('serial_number', '').strip()

        if not bjo_id or not serial_number:
            messages.error(request, "BJO dan Serial Number wajib diisi.")
            return redirect('manual_add_pin_protector')

        bjo = JobHeader.objects.filter(id=bjo_id).first()
        if not bjo:
            messages.error(request, "BJO tidak ditemukan.")
            return redirect('manual_add_pin_protector')

        # Cek apakah qty sudah penuh
        existing_count = PinProtector.objects.filter(bjo=bjo).count()
        max_allowed = bjo.qty or 0

        if existing_count >= max_allowed:
            messages.error(request, f"Tidak dapat menambah pin protector. Jumlah sudah mencapai batas maksimal ({max_allowed}).")
            return redirect('manual_add_pin_protector')

        # Cek duplikat GLOBAL - di semua BJO, bukan hanya BJO yang dipilih
        existing_pin = PinProtector.objects.filter(serial_number=serial_number).first()
        if existing_pin:
            messages.error(request, f"Serial Number '{serial_number}' sudah digunakan di BJO {existing_pin.bjo.bjo}. Pilih nomor lain.")
            return redirect('manual_add_pin_protector')

        # Gunakan transaction untuk konsistensi data
        try:
            with transaction.atomic():
                # Simpan pin protector
                PinProtector.objects.create(
                    bjo=bjo,
                    serial_number=serial_number,
                    is_used=False
                )

                # Hitung informasi untuk pesan
                total_generated = existing_count + 1
                remaining_after = max_allowed - total_generated
                progress_percentage = (total_generated / max_allowed * 100) if max_allowed > 0 else 0
                
                success_msg = f"Serial Number '{serial_number}' berhasil ditambahkan. "
                success_msg += f"Progress BJO: {total_generated}/{int(max_allowed)} ({progress_percentage:.1f}%) - Sisa slot: {remaining_after}"
                
                # Cek apakah job sudah complete
                if remaining_after == 0:
                    success_msg += " - BJO COMPLETED!"
                    
                messages.success(request, success_msg)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan saat menambah pin protector: {str(e)}")
            return redirect('manual_add_pin_protector')

        return redirect('manual_add_pin_protector')

    # Tambahkan informasi existing count untuk setiap BJO
    jobheaders = JobHeader.objects.filter(bjo_for='PIN PROTECTOR')
    for header in jobheaders:
        header.existing_count = PinProtector.objects.filter(bjo=header).count()
        header.remaining_slots = (header.qty or 0) - header.existing_count
        
    context = {
        'jobheaders': jobheaders,
        'active_menu': 'pinprotector_list',
    }

    return render(request, 'pinprotector/manual_add.html', context)

@pinprotector_access_required
def pinprotector_list(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    filter_threaded = request.GET.get('threaded', '')
    filter_beveled = request.GET.get('beveled', '')
    per_page = request.GET.get('per_page', '10')

    # Validasi parameter per_page
    try:
        per_page = int(per_page)
        if per_page not in [10, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    # ============ AMBIL DATA AWAL ============
    items = PinProtector.objects.select_related('bjo').order_by('-created_at')
    if query:
        items = items.filter(
            Q(serial_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )

    # Filter BJO
    if filter_bjo:
        items = items.filter(bjo__id=filter_bjo)
    items_for_count = items
    
    status_counts = items_for_count.aggregate(
        threaded=Count('id', filter=Q(is_threaded=True)),
        beveled=Count('id', filter=Q(is_beveled=True)),
        phosphated=Count('id', filter=Q(is_used=True)),
        ncr=Count('id', filter=Q(is_ncr=True)),
        rwk=Count('id', filter=Q(is_rwk=True)),
    )

    # Filter Threaded (SETELAH hitung status)
    if filter_threaded:
        if filter_threaded == 'true':
            items = items.filter(is_threaded=True)
        elif filter_threaded == 'false':
            items = items.filter(is_threaded=False)

    # Filter Beveled (SETELAH hitung status)
    if filter_beveled:
        if filter_beveled == 'true':
            items = items.filter(is_beveled=True)
        elif filter_beveled == 'false':
            items = items.filter(is_beveled=False)

    # Total data (setelah SEMUA filter termasuk threaded dan beveled)
    total_filtered = items.count()

    # Pagination
    paginator = Paginator(items, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Filter BJO hanya untuk PIN PROTECTOR
    bjo_list = JobHeader.objects.filter(bjo_for='PIN PROTECTOR')

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_threaded': filter_threaded,
        'filter_beveled': filter_beveled,
        'per_page': str(per_page),
        'bjo_list': bjo_list,
        'active_menu': 'pinprotector_list',
        'status_counts': status_counts,
        'total_filtered': total_filtered,
    }

    return render(request, 'pinprotector/list.html', context)

@pinprotector_pdf_access_required
def pinprotector_pdf(request):
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')

    items = PinProtector.objects.select_related('bjo').order_by('-created_at')

    if query:
        items = items.filter(
            Q(serial_number__icontains=query) |
            Q(bjo__customer__icontains=query)
        )

    if filter_bjo:
        items = items.filter(bjo__id=filter_bjo)

    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))
    today = date.today()

    template_path = 'pinprotector/pdf.html'
    context = {
        'items': items,
        'logo_url': logo_url,
        'today': today,
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="pin_protector_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@pinprotector_write_access_required
def pinprotector_edit(request, pk):
    item = get_object_or_404(PinProtector, pk=pk)

    # Jika pin protector sudah threaded DAN phosphated, tidak boleh diedit
    if item.is_threaded and item.is_used:
        messages.warning(request, f"PIN Protector {item.serial_number} sudah di-threaded dan phosphated, tidak dapat diedit.")
        # Tetap tampilkan halaman edit tapi dalam mode read-only
        
        # Hitung remaining slots untuk display saja
        jobheaders_with_remaining = []
        for jobheader in JobHeader.objects.filter(bjo_for='PIN PROTECTOR'):
            existing_count = PinProtector.objects.filter(bjo=jobheader).count()
            remaining_slots = jobheader.qty - existing_count
            jobheader.remaining_slots = remaining_slots
            jobheader.existing_count = existing_count
            jobheaders_with_remaining.append(jobheader)

        context = {
            'item': item,
            'jobheaders': jobheaders_with_remaining,
            'active_menu': 'pinprotector_list',
        }
        return render(request, 'pinprotector/edit.html', context)

    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        new_bjo = JobHeader.objects.filter(id=bjo_id, bjo_for='PIN PROTECTOR').first()
        if not new_bjo:
            messages.error(request, "BJO PIN PROTECTOR tidak valid.")
            return redirect('pinprotector_list')

        new_serial_number = request.POST.get('serial_number', '').strip()
        
        # Validasi serial number tidak boleh kosong
        if not new_serial_number:
            messages.error(request, "Serial Number tidak boleh kosong.")
            return redirect('pinprotector_edit', pk=pk)

        # Cek duplikat GLOBAL - kecuali serial number yang sedang diedit
        existing_pin = PinProtector.objects.filter(serial_number=new_serial_number).exclude(pk=item.pk).first()
        if existing_pin:
            messages.error(request, f"Serial Number {new_serial_number} sudah digunakan di BJO {existing_pin.bjo.bjo}. Pilih nomor lain.")
            return redirect('pinprotector_edit', pk=pk)

        # Jika mengganti BJO, cek apakah BJO baru memiliki slot tersisa
        if item.bjo != new_bjo:
            # Hitung slot tersisa untuk BJO baru
            existing_count = PinProtector.objects.filter(bjo=new_bjo).count()
            remaining_slots = new_bjo.qty - existing_count
            
            if remaining_slots <= 0:
                messages.error(request, f"BJO {new_bjo.bjo} sudah penuh. Tidak dapat memindahkan pin protector ke BJO ini.")
                return redirect('pinprotector_edit', pk=pk)

        item.bjo = new_bjo
        item.serial_number = new_serial_number
        # Jangan ubah is_used dari form
        item.save()
        messages.success(request, "PIN Protector berhasil diperbarui.")
        return redirect('pinprotector_list')

    # Hitung remaining slots untuk setiap JobHeader
    jobheaders_with_remaining = []
    for jobheader in JobHeader.objects.filter(bjo_for='PIN PROTECTOR'):
        existing_count = PinProtector.objects.filter(bjo=jobheader).count()
        remaining_slots = jobheader.qty - existing_count
        
        # Jika ini adalah BJO yang sedang digunakan oleh item, tambah 1 ke remaining
        # karena setelah edit, slot dari item ini akan kosong
        if item.bjo == jobheader:
            remaining_slots += 1
            
        jobheader.remaining_slots = remaining_slots
        jobheader.existing_count = existing_count
        jobheaders_with_remaining.append(jobheader)

    context = {
        'item': item,
        'jobheaders': jobheaders_with_remaining,
        'active_menu': 'pinprotector_list',
    }
    return render(request, 'pinprotector/edit.html', context)
    
@pinprotector_delete_access_required
def delete_pinprotector(request, id):
    """
    View untuk menghapus Pin Protector
    """
    if request.method == 'POST':
        try:
            pin_protector = get_object_or_404(PinProtector, id=id)
            serial_number_name = pin_protector.serial_number
            pin_protector.delete()
            
            messages.success(request, f'Serial Number {serial_number_name} berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('pinprotector_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('bjo'):
                query_params.append(f"bjo={request.GET.get('bjo')}")
            if request.GET.get('threaded'):
                query_params.append(f"threaded={request.GET.get('threaded')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Serial Number: {str(e)}')
            return redirect('pinprotector_list')
    
    return redirect('pinprotector_list')

def bookedhours_list(request):
    query = request.GET.get('q', '')
    items = BookedHours.objects.all().order_by('-created_at')

    if query:
        items = items.filter(Q(name__icontains=query))

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'booked_hours',
    }
    return render(request, 'bookedhours/list.html', context)

def bookedhours_add(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        duration = request.POST.get('duration')

        if not name or not duration:
            messages.error(request, "Semua field wajib diisi.")
            return redirect('bookedhours_add')

        BookedHours.objects.create(name=name, duration=duration)
        messages.success(request, "Booked Hours berhasil ditambahkan.")
        return redirect('bookedhours_list')

    return render(request, 'bookedhours/add.html', {'active_menu': 'booked_hours'}) 

def bookedhours_edit(request, pk):
    item = get_object_or_404(BookedHours, pk=pk)

    if request.method == 'POST':
        item.name = request.POST.get('name')
        item.duration = request.POST.get('duration')

        if not item.name or not item.duration:
            messages.error(request, "Semua field wajib diisi.")
            return redirect('bookedhours_edit', pk=pk)

        item.save()
        messages.success(request, "Booked Hours berhasil diperbarui.")
        return redirect('bookedhours_list')

    return render(request, 'bookedhours/edit.html', {
    'item': item,
    'active_menu': 'booked_hours'
})
    
def bookedhours_delete(request, id):
    if request.method == 'POST':
        try:
            booked_hours = get_object_or_404(BookedHours, id=id)
            name = booked_hours.name
            booked_hours.delete()
            
            messages.success(request, f'Booked Hours "{name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('bookedhours_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Booked Hours: {str(e)}')
            return redirect('bookedhours_list')
    
    return redirect('bookedhours_list')

def connection_list(request):
    query = request.GET.get('q', '')
    connection_qs = Connection.objects.all()

    if query:
        connection_qs = connection_qs.filter(
            Q(name__icontains=query) |
            Q(remarks__icontains=query)
        )

    paginator = Paginator(connection_qs, 10)
    page = request.GET.get('page')
    items = paginator.get_page(page)

    return render(request, 'connection/list.html', {
        'items': items,
        'query': query,
        'active_menu': 'connection',
    })

def connection_add(request):
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            remarks = request.POST.get('remarks', '')
            
            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Connection tidak boleh kosong.')
                return render(request, 'connection/generate.html', {'active_menu': 'connection'})
            
            # Cek apakah nama sudah ada
            if Connection.objects.filter(name=name).exists():
                messages.error(request, f'Connection dengan nama "{name}" sudah ada.')
                return render(request, 'connection/generate.html', {
                    'active_menu': 'connection',
                    'name': name,
                    'remarks': remarks
                })
            
            Connection.objects.create(name=name, remarks=remarks)
            messages.success(request, f'Connection "{name}" berhasil ditambahkan.')
            return redirect('connection_list')
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Connection: {str(e)}')
            return render(request, 'connection/generate.html', {'active_menu': 'connection'})
    
    return render(request, 'connection/generate.html', {'active_menu': 'connection'})

def connection_edit(request, pk):
    item = get_object_or_404(Connection, pk=pk)
    
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            remarks = request.POST.get('remarks', '')
            
            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Connection tidak boleh kosong.')
                return render(request, 'connection/edit.html', {
                    'item': item, 
                    'active_menu': 'connection'
                })
            
            # Cek apakah nama sudah ada (kecuali untuk item yang sedang diedit)
            if Connection.objects.filter(name=name).exclude(pk=pk).exists():
                messages.error(request, f'Connection dengan nama "{name}" sudah ada.')
                return render(request, 'connection/edit.html', {
                    'item': item, 
                    'active_menu': 'connection'
                })
            
            # Update data
            old_name = item.name
            item.name = name
            item.remarks = remarks
            item.save()
            
            messages.success(request, f'Connection "{old_name}" berhasil diperbarui menjadi "{name}".')
            return redirect('connection_list')
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Connection: {str(e)}')
            return render(request, 'connection/edit.html', {
                'item': item, 
                'active_menu': 'connection'
            })
    
    return render(request, 'connection/edit.html', {
        'item': item, 
        'active_menu': 'connection'
    })

def connection_delete(request, id):
    """
    View untuk menghapus Connection
    """
    if request.method == 'POST':
        try:
            connection = get_object_or_404(Connection, id=id)
            name = connection.name
            connection.delete()
            
            messages.success(request, f'Connection "{name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('connection_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Connection: {str(e)}')
            return redirect('connection_list')
    
    return redirect('connection_list')

@threading_access_required
def thread_list(request):
    """List semua ThreadHeader dengan filter dan pagination"""
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')
    filter_bjo = request.GET.get('bjo', '')

    headers = ThreadHeader.objects.select_related(
        'machine', 'shift', 'operator', 'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    # Filter by BJO
    if filter_bjo:
        headers = headers.filter(
            id__in=ThreadDetail.objects.filter(
                Q(bjo_number__icontains=filter_bjo) |
                Q(bjo__bjo__icontains=filter_bjo)
            ).values_list('Reff_id', flat=True)
        )

    headers = headers.order_by('-date', '-id')
    
    # Hitung actual_hours dan total output
    for header in headers:
        if not header.is_posted:
            detail_qs = ThreadDetail.objects.filter(Reff=header)
            total_hours = 0
            total_output = 0
            
            for detail in detail_qs:
                if detail.start_time and detail.stop_time:
                    duration_hours = calculate_time_duration(detail.start_time, detail.stop_time)
                    if duration_hours:
                        total_hours += duration_hours
                
                if detail.output:
                    total_output += float(detail.output)
            
            header.calculated_actual_hours = round(total_hours, 2)
            header.calculated_actual_output = round(total_output, 2)
        else:
            header.calculated_actual_hours = float(header.actual_hours) if header.actual_hours else 0
            header.calculated_actual_output = float(header.actual_output) if header.actual_output else 0
    
    paginator = Paginator(headers, 100)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    machine_options = Machine.objects.filter(
        process_type__name__icontains='threading'
    ).values_list('name', flat=True).distinct().order_by('name')

    # NEW: Get distinct BJO numbers for filter dropdown
    bjo_options = ThreadDetail.objects.filter(
        bjo_number__isnull=False
    ).exclude(
        bjo_number=''
    ).values_list('bjo_number', flat=True).distinct().order_by('bjo_number')

    status_options = [
        ('', '-- All Status --'),
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ]

    context = {
        'headers': page_obj,
        'query': query,
        'filter_machine': filter_machine,
        'filter_date': filter_date,
        'filter_status': filter_status,
        'filter_bjo': filter_bjo,
        'machine_options': machine_options,
        'bjo_options': bjo_options,
        'status_options': status_options,
        'active_menu': 'thread_list',
    }

    return render(request, 'thread/list.html', context)

@threading_write_access_required
def thread_delete(request, header_id):
    """Delete ThreadHeader - hanya boleh jika belum posted"""
    header = get_object_or_404(ThreadHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            # Cek apakah sudah posted
            if header.is_posted:
                messages.error(request, 'Data tidak dapat dihapus karena sudah di-posting.')
                return redirect('thread_list')
            
            # Simpan informasi untuk pesan sebelum menghapus
            thread_info = f"{header.machine.name} - {header.date.strftime('%d/%m/%Y')}"
            
            # Hapus data header beserta semua detail yang terkait
            # Django akan otomatis menghapus ThreadDetail yang berelasi karena ForeignKey
            header.delete()
            
            messages.success(request, f'Record threading {thread_info} berhasil dihapus.')
            return redirect('thread_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('thread_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('thread_list')

@threading_write_access_required
def thread_header(request):
    """Create new ThreadHeader record with minimal fields"""
    if request.method == 'POST':
        required_fields = ['date', 'machine', 'shift', 'operator', 'booked_hours']
        missing_fields = [f.replace('_', ' ').title() for f in required_fields if not request.POST.get(f)]

        if missing_fields:
            messages.error(request, f"Field wajib yang belum diisi: {', '.join(missing_fields)}")
        else:
            try:
                # Validasi tanggal
                try:
                    date_obj = datetime.strptime(request.POST.get('date'), "%Y-%m-%d").date()
                except ValueError:
                    messages.error(request, "Format tanggal tidak valid.")
                    return render(request, 'thread/header.html', get_context_data(request.user))

                # Ambil foreign keys
                try:
                    machine = Machine.objects.get(id=request.POST.get('machine'))
                    shift = Shift.objects.get(id=request.POST.get('shift'))
                    operator = Operator.objects.get(id=request.POST.get('operator'))
                    booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
                except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                    messages.error(request, "Data yang dipilih tidak valid.")
                    return render(request, 'thread/header.html', get_context_data(request.user))

                # Buat record baru
                header = ThreadHeader.objects.create(
                    date=date_obj,
                    machine=machine,
                    shift=shift,
                    operator=operator,
                    booked_hours=booked_hours
                )

                messages.success(request, "Threading Record berhasil disimpan.")
                # Redirect sesuai URL pattern yang benar
                return redirect('thread_detail', header_id=header.pk)

            except Exception as e:
                messages.error(request, f"Terjadi kesalahan: {str(e)}")

    return render(request, 'thread/header.html', get_context_data(request.user))

def get_context_data(user, for_edit=False):
    """Data untuk form Thread Header"""
    # Filter mesin untuk THREADING process
    threading_machines = Machine.objects.filter(
        process_type__name__icontains='threading'
    ).order_by('name')

    # Filter operator berdasarkan position = 'THREAD'
    threading_operators = Operator.objects.filter(
        position='THREAD'
    ).order_by('name')
    
    # Fallback jika tidak ada operator dengan position THREAD
    if not threading_operators.exists():
        threading_operators = Operator.objects.all().order_by('name')
    
    # Booked hours logic
    if user.role in ['admin', 'supervisor', 'leadman'] or for_edit:
        booked_hours_list = BookedHours.objects.all().order_by('name')
    else:
        # Operator saat create: hanya 4 opsi utama
        allowed_booked_hours = [
            'FRIDAY NORMAL',
            'FRIDAY OT', 
            'NORMAL',
            'OT'
        ]
        booked_hours_list = BookedHours.objects.filter(
            name__in=allowed_booked_hours
        ).order_by('name')

    return {
        'machine_list': threading_machines,
        'shift_list': Shift.objects.all().order_by('name'),
        'operator_list': threading_operators,
        'booked_hours_list': booked_hours_list,
    }

@threading_write_access_required
def thread_edit(request, header_id):
    """Edit ThreadHeader - dengan auto revert posted status ketika ada perubahan"""
    header = get_object_or_404(ThreadHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit posted records.'
            )
            return redirect('thread_list')

    if request.method == 'POST':
        try:
            # Validasi tanggal
            try:
                date_obj = datetime.strptime(request.POST.get('date'), "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Format tanggal tidak valid.")
                return render(request, 'thread/edit.html', {**get_context_data(request.user, for_edit=True), 'header': header})

            # Ambil foreign keys
            try:
                machine = Machine.objects.get(id=request.POST.get('machine'))
                shift = Shift.objects.get(id=request.POST.get('shift'))
                operator = Operator.objects.get(id=request.POST.get('operator'))
                booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
            except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                messages.error(request, "Data yang dipilih tidak valid.")
                return render(request, 'thread/edit.html', {**get_context_data(request.user, for_edit=True), 'header': header})

            # ===== CEK APAKAH ADA PERUBAHAN DATA =====
            has_changes = (
                header.date != date_obj or
                header.machine != machine or
                header.shift != shift or
                header.operator != operator or
                header.booked_hours != booked_hours
            )

            # ===== AUTO REVERT POSTED STATUS JIKA ADA PERUBAHAN =====
            if has_changes and header.is_posted:
                header.is_posted = False
                messages.warning(
                    request,
                    "Status record telah dikembalikan ke DRAFT karena ada perubahan header."
                )

            # Update record
            header.date = date_obj
            header.machine = machine
            header.shift = shift
            header.operator = operator
            header.booked_hours = booked_hours
            header.save()

            if has_changes:
                messages.success(request, "Threading Record berhasil diperbarui.")
            else:
                messages.info(request, "Tidak ada perubahan data.")
            
            return redirect('thread_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")

    context = get_context_data(request.user, for_edit=True)
    context['header'] = header
    return render(request, 'thread/edit.html', context)

def calculate_thread_output(bjo, pin_or_box, is_uncompleted):
    """
    Calculate output value based on BJO type and completion status
    OUTPUT UNTUK LAPORAN PRODUKSI:
    - Semua jenis: 1 (completed) atau 0.5 (uncompleted)
    """
    def detect_bjo_type(bjo):
        bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
        product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        if bjo_for:
            if 'BOX' in bjo_for:
                return 'box'
            elif 'PIN' in bjo_for:
                return 'pin'
            elif 'PIPE' in bjo_for or 'THREADING' in bjo_for:
                return 'pipe'
        
        if product and not bjo_for:
            if 'BOX' in product:
                return 'box'
            elif 'PIN' in product:
                return 'pin'
        
        if process_name and not bjo_for and not product:
            if 'BOX' in process_name:
                return 'box'
            elif 'PIN' in process_name:
                return 'pin'
        
        return 'pipe'

    bjo_type = detect_bjo_type(bjo)
    
    # SEMUA JENIS (pipe, box, pin): 0.5 untuk uncompleted, 1 untuk completed
    return 0.5 if is_uncompleted else 1.0

def get_bjo_connector_info(request):
    """Check if BJO requires connector number"""
    bjo_id = request.GET.get('bjo_id')
    
    if not bjo_id:
        return JsonResponse({'requires_connector': False})
    
    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        requires_connector = False
        if 'THREAD' in process_name:
            conn_name = bjo.conn.name.upper() if bjo.conn else ''
            valid_connections = ['XLW-S', 'XLW-GT', 'XLW']
            requires_connector = any(vc in conn_name for vc in valid_connections)
        
        return JsonResponse({
            'requires_connector': requires_connector,
            'process': process_name,
            'connection': bjo.conn.name if bjo.conn else None
        })
    except JobHeader.DoesNotExist:
        return JsonResponse({'requires_connector': False, 'error': 'BJO not found'})
    
def get_connector_number(request):
    """Get existing connector number for a joint"""
    bjo_id = request.GET.get('bjo_id')
    joint_number = request.GET.get('joint_number')
    
    if not bjo_id or not joint_number:
        return JsonResponse({'conn_number': None})
    
    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        connector = Connector.objects.filter(
            bjo=bjo,
            joint_number=joint_number
        ).first()
        
        if connector:
            return JsonResponse({
                'conn_number': connector.conn_number,
                'exists': True
            })
        else:
            return JsonResponse({
                'conn_number': None,
                'exists': False
            })
    except JobHeader.DoesNotExist:
        return JsonResponse({'conn_number': None, 'error': 'BJO not found'})

@threading_access_required
def thread_detail(request, header_id):
    header = get_object_or_404(ThreadHeader, pk=header_id)

    if request.method == 'POST':
        # ===== CEK AKSES UNTUK POSTED RECORDS =====
        if header.is_posted:
            if request.user.role not in ['admin', 'supervisor']:
                messages.error(
                    request, 
                    "Access Denied: Only Admin and Supervisor can modify posted records."
                )
                return redirect('thread_detail', header_id=header.id)
            else:
                # ===== AUTO REVERT POSTED STATUS =====
                header.is_posted = False
                header.save(update_fields=['is_posted'])
                messages.warning(
                    request,
                    "Status record telah dikembalikan ke DRAFT karena ada perubahan data."
                )
        
        action = request.POST.get('action')
        
        if action == 'update_consumable':
            return handle_update_consumable(request, header)
        
        if action == 'edit_time':
            return handle_edit_time_thread_detail(request, header_id)
        
        if action == 'edit':
            return handle_edit_thread_detail(request, header_id)

        try:
            with transaction.atomic():
                start_time_str = request.POST.get('start_time')
                stop_time_str = request.POST.get('stop_time')

                if not start_time_str or not stop_time_str:
                    messages.error(request, "Start Time dan Stop Time wajib diisi.")
                    return redirect('thread_detail', header_id=header.id)

                try:
                    start_time = datetime.strptime(start_time_str, '%H:%M').time()
                    stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
                except ValueError:
                    messages.error(request, "Format waktu tidak valid.")
                    return redirect('thread_detail', header_id=header.id)

                start_minutes = start_time.hour * 60 + start_time.minute
                stop_minutes = stop_time.hour * 60 + stop_time.minute

                if start_time == stop_time:
                    messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
                    return redirect('thread_detail', header_id=header.id)

                if stop_minutes < start_minutes:
                    duration = (stop_minutes + 24 * 60) - start_minutes
                else:
                    duration = stop_minutes - start_minutes

                if duration > 24 * 60:
                    messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
                    return redirect('thread_detail', header_id=header.id)

                bjo_id = request.POST.get('bjo')
                if not bjo_id:
                    messages.error(request, "BJO wajib dipilih.")
                    return redirect('thread_detail', header_id=header.id)

                try:
                    bjo = JobHeader.objects.get(id=bjo_id)
                except JobHeader.DoesNotExist:
                    messages.error(request, "BJO yang dipilih tidak valid.")
                    return redirect('thread_detail', header_id=header.id)

                pin_or_box_raw = request.POST.get('pin_or_box')
                if not pin_or_box_raw:
                    messages.error(request, "Pin/Box wajib dipilih.")
                    return redirect('thread_detail', header_id=header.id)

                pin_or_box = pin_or_box_raw.replace(' (REWORK)', '').strip()
                is_rework_from_selection = ' (REWORK)' in pin_or_box_raw
                
                if pin_or_box not in ['PIN', 'BOX']:
                    messages.error(request, "Pin/Box harus PIN atau BOX.")
                    return redirect('thread_detail', header_id=header.id)

                job_operation = request.POST.get('job_operation', '').strip()
                if not job_operation:
                    messages.error(request, "Job Operation wajib diisi.")
                    return redirect('thread_detail', header_id=header.id)
                
                if len(job_operation) > 3:
                    messages.error(request, "Job Operation maksimal 3 karakter.")
                    return redirect('thread_detail', header_id=header.id)

                ct = None
                ct_str = request.POST.get('ct')
                if ct_str:
                    try:
                        ct = float(ct_str)
                        if ct < 0:
                            messages.error(request, "CT tidak boleh negatif.")
                            return redirect('thread_detail', header_id=header.id)
                    except ValueError:
                        messages.error(request, "CT harus berupa angka.")
                        return redirect('thread_detail', header_id=header.id)
                
                pb = None
                pb_str = request.POST.get('pb')
                if pb_str:
                    try:
                        pb = float(pb_str)
                        if pb < 0:
                            messages.error(request, "PB tidak boleh negatif.")
                            return redirect('thread_detail', header_id=header.id)
                    except ValueError:
                        messages.error(request, "PB harus berupa angka.")
                        return redirect('thread_detail', header_id=header.id)

                is_uncompleted = request.POST.get('is_uncompleted') == 'on'

                joint_number = request.POST.get('joint_number', '').strip()
                if not joint_number:
                    messages.error(request, "Joint Number wajib dipilih.")
                    return redirect('thread_detail', header_id=header.id)

                # ===== HANDLE CONNECTOR NUMBER =====
                conn_number = None
                process_name = bjo.process_type.name.upper() if bjo.process_type else ''
                
                # Cek apakah BJO ini memerlukan connector
                requires_connector = False
                if 'THREAD' in process_name:
                    conn_name = bjo.conn.name.upper() if bjo.conn else ''
                    valid_connections = ['XLW-S', 'XLW-GT', 'XLW']
                    requires_connector = any(vc in conn_name for vc in valid_connections)
                
                if requires_connector:
                    conn_number_raw = request.POST.get('conn_number', '')
                    
                    # ✅ CLEAN: Hapus semua spasi dari conn_number
                    conn_number = clean_conn_number(conn_number_raw)
                    
                    if not conn_number:
                        messages.error(request, "Connector Number wajib diisi untuk BJO dengan connection XLW-S, XLW-GT, atau XLW.")
                        return redirect('thread_detail', header_id=header.id)
                    
                    # Validasi: Cek apakah joint number valid untuk BJO ini
                    joint_exists = SerialNumber.objects.filter(
                        bjo=bjo,
                        joint_number=joint_number
                    ).exists()
                    
                    if not joint_exists:
                        messages.error(
                            request,
                            f"Joint Number '{joint_number}' tidak ditemukan pada BJO '{bjo.bjo}'."
                        )
                        return redirect('thread_detail', header_id=header.id)
                    
                    # ✅ VALIDASI BARU: conn_number harus unique, KECUALI untuk BJO + Joint Number yang sama
                    existing_conn = Connector.objects.filter(conn_number=conn_number).exclude(
                        bjo=bjo,
                        joint_number=joint_number
                    ).first()

                    if existing_conn:
                        messages.error(
                            request,
                            f"Connector Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                            f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
                        )
                        return redirect('thread_detail', header_id=header.id)
                    
                    # Cek duplikasi connector untuk joint number ini
                    existing_connector = Connector.objects.filter(
                        bjo=bjo,
                        joint_number=joint_number
                    ).first()
                    
                    if existing_connector:
                        # ✅ VALIDASI: Jika sudah ada, conn_number harus sama
                        if existing_connector.conn_number != conn_number:
                            messages.error(
                                request,
                                f"BJO '{bjo.bjo}' Joint '{joint_number}' sudah memiliki Connector Number "
                                f"'{existing_connector.conn_number}'. Tidak bisa menggunakan nomor berbeda. "
                                f"Gunakan nomor yang sama atau pilih joint number lain."
                            )
                            return redirect('thread_detail', header_id=header.id)
                        else:
                            # Jika conn_number sama, gunakan yang existing
                            conn_number = existing_connector.conn_number
                    # Jika belum ada, akan dibuat setelah ThreadDetail berhasil disimpan

                def detect_bjo_type(bjo):
                    bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
                    product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
                    process_name = bjo.process_type.name.upper() if bjo.process_type else ''
                    
                    if bjo_for:
                        if 'BOX' in bjo_for:
                            return 'box'
                        elif 'PIN' in bjo_for:
                            return 'pin'
                        elif 'PIPE' in bjo_for or 'THREADING' in bjo_for:
                            return 'pipe'
                    
                    if product and not bjo_for:
                        if 'BOX' in product:
                            return 'box'
                        elif 'PIN' in product:
                            return 'pin'
                    
                    if process_name and not bjo_for and not product:
                        if 'BOX' in process_name:
                            return 'box'
                        elif 'PIN' in process_name:
                            return 'pin'
                    
                    return 'pipe'

                bjo_type = detect_bjo_type(bjo)

                # ===== CEK INFO TAG (HANYA UNTUK DISPLAY) =====
                info_tag_name = bjo.info.name.upper() if bjo.info else ''
                is_bxb = 'B X B' in info_tag_name or 'BXB' in info_tag_name
                is_pxp = 'P X P' in info_tag_name or 'PXP' in info_tag_name
                
                # Simpan info tag untuk display nanti
                info_tag_display = None
                if is_bxb:
                    info_tag_display = 'B X B'
                elif is_pxp:
                    info_tag_display = 'P X P'

                # Cek remaining qty (calculated), bukan qty asli
                from decimal import Decimal
                total_finished = jobDetail.objects.filter(job=bjo).aggregate(
                    total=Sum('finished')
                )['total'] or Decimal(0)
                remaining_qty = float(bjo.qty) - float(total_finished)

                if bjo_type == 'pipe':
                    required_qty = 0.25 if is_uncompleted else 0.5
                    qty_check_message = "0.25" if is_uncompleted else "0.5"
                else:
                    required_qty = 0.5 if is_uncompleted else 1.0
                    qty_check_message = "0.5" if is_uncompleted else "1"

                if remaining_qty < required_qty:
                    messages.error(request, f"Remaining quantity BJO {bjo.bjo} tidak mencukupi ({remaining_qty}). Minimal dibutuhkan {qty_check_message} untuk threading.")
                    return redirect('thread_detail', header_id=header.id)

                protector_type = None
                is_rework = False
                is_merge_rework = False
                is_completing_uncompleted = False
                rework_detail = None
                uncompleted_detail = None
                uncompleted_same_header = False

                if bjo_type == 'box':
                    try:
                        protector = BoxProtector.objects.get(serial_number=joint_number, bjo=bjo)
                        protector_type = 'box'
                        
                        existing_uncompleted = ThreadDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo,
                            pin_or_box='BOX',
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                            
                        elif protector.is_threaded and protector.is_ncr and not protector.is_rwk:
                            existing_detail_same_header = ThreadDetail.objects.filter(
                                Reff=header,
                                joint_number=joint_number,
                                bjo=bjo,
                                pin_or_box='BOX',
                                is_uncompleted=False
                            ).first()
                            
                            if existing_detail_same_header:
                                is_rework = True
                                is_merge_rework = True
                                rework_detail = existing_detail_same_header
                            else:
                                is_rework = True
                                is_merge_rework = False
                                BoxProtector.objects.filter(
                                    serial_number=joint_number, 
                                    bjo=bjo
                                ).update(is_rwk=True)
                        elif protector.is_threaded and protector.is_rwk:
                            messages.error(request, f"BOX Protector '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                            return redirect('thread_detail', header_id=header.id)
                        elif protector.is_threaded and not protector.is_ncr and not existing_uncompleted:
                            messages.error(request, f"BOX Protector '{joint_number}' sudah pernah di-thread dan bukan NCR.")
                            return redirect('thread_detail', header_id=header.id)
                            
                    except BoxProtector.DoesNotExist:
                        messages.error(request, f"BOX Protector '{joint_number}' tidak ditemukan.")
                        return redirect('thread_detail', header_id=header.id)
                        
                    if pin_or_box != 'BOX':
                        messages.error(request, f"BJO ini hanya untuk BOX threading.")
                        return redirect('thread_detail', header_id=header.id)
                        
                elif bjo_type == 'pin':
                    try:
                        protector = PinProtector.objects.get(serial_number=joint_number, bjo=bjo)
                        protector_type = 'pin'
                        
                        existing_uncompleted = ThreadDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo,
                            pin_or_box='PIN',
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                            
                        elif protector.is_threaded and protector.is_ncr and not protector.is_rwk:
                            existing_detail_same_header = ThreadDetail.objects.filter(
                                Reff=header,
                                joint_number=joint_number,
                                bjo=bjo,
                                pin_or_box='PIN',
                                is_uncompleted=False
                            ).first()
                            
                            if existing_detail_same_header:
                                is_rework = True
                                is_merge_rework = True
                                rework_detail = existing_detail_same_header
                            else:
                                is_rework = True
                                is_merge_rework = False
                                PinProtector.objects.filter(
                                    serial_number=joint_number, 
                                    bjo=bjo
                                ).update(is_rwk=True)
                        elif protector.is_threaded and protector.is_rwk:
                            messages.error(request, f"PIN Protector '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                            return redirect('thread_detail', header_id=header.id)
                        elif protector.is_threaded and not protector.is_ncr and not existing_uncompleted:
                            messages.error(request, f"PIN Protector '{joint_number}' sudah pernah di-thread dan bukan NCR.")
                            return redirect('thread_detail', header_id=header.id)
                            
                    except PinProtector.DoesNotExist:
                        messages.error(request, f"PIN Protector '{joint_number}' tidak ditemukan.")
                        return redirect('thread_detail', header_id=header.id)
                        
                    if pin_or_box != 'PIN':
                        messages.error(request, f"BJO ini hanya untuk PIN threading.")
                        return redirect('thread_detail', header_id=header.id)
                else:
                    # ===== PIPE LOGIC - FIXED FOR REWORK AFTER COMPLETION =====
                    try:
                        serial = SerialNumber.objects.get(joint_number=joint_number, bjo=bjo)
                        protector_type = 'pipe'
                        
                        # Cek UNCOMPLETED terlebih dahulu
                        existing_uncompleted = ThreadDetail.objects.filter(
                            joint_number=joint_number,
                            pin_or_box=pin_or_box,
                            bjo=bjo,
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            # COMPLETING UNCOMPLETED
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                        else:
                            # Cek existing COMPLETED detail (yang bukan UNCOMPLETED)
                            existing_detail = ThreadDetail.objects.filter(
                                joint_number=joint_number,
                                pin_or_box=pin_or_box,
                                bjo=bjo,
                                is_uncompleted=False
                            ).order_by('-id').first()  # Ambil yang terbaru
                            
                            if existing_detail:
                                # Cek apakah sudah pernah rework
                                if serial.is_rwk:
                                    messages.error(request, f"Sisi {pin_or_box} untuk joint '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                                    return redirect('thread_detail', header_id=header.id)
                                
                                # ✅ CRITICAL FIX: Cek NCR pada existing_detail (record COMPLETED terbaru)
                                # BUKAN dari serial.is_ncr karena bisa outdated
                                has_existing_ncr = ThreadNcr.objects.filter(serial=existing_detail).exists()
                                
                                if has_existing_ncr:
                                    # REWORK LOGIC - Ada NCR, boleh dirework
                                    if existing_detail.Reff == header:
                                        # MERGE REWORK di header yang sama
                                        is_rework = True
                                        is_merge_rework = True
                                        rework_detail = existing_detail
                                    else:
                                        # REWORK BARU di header berbeda
                                        is_rework = True
                                        is_merge_rework = False
                                        SerialNumber.objects.filter(
                                            joint_number=joint_number, 
                                            bjo=bjo
                                        ).update(is_rwk=True)
                                else:
                                    # Detail sudah ada tapi TIDAK ada NCR
                                    messages.error(request, f"Sisi {pin_or_box} untuk joint '{joint_number}' sudah diinput dan bukan NCR.")
                                    return redirect('thread_detail', header_id=header.id)
                        
                    except SerialNumber.DoesNotExist:
                        messages.error(request, f"Joint Number '{joint_number}' tidak ditemukan untuk BJO yang dipilih.")
                        return redirect('thread_detail', header_id=header.id)

                comment = request.POST.get('comment', '').strip()

                # ========== PROSES COMPLETING UNCOMPLETED ==========
                if is_completing_uncompleted and uncompleted_detail:
                    old_comment = uncompleted_detail.comment or ''
                    
                    if uncompleted_same_header:
                        if comment:
                            merged_comment = f"COMPLETED | {comment}"
                            if old_comment and not old_comment.startswith('UNCOMPLETED'):
                                merged_comment = f"{old_comment} | COMPLETED | {comment}"
                        else:
                            merged_comment = "COMPLETED"
                            if old_comment:
                                merged_comment = f"{old_comment} | COMPLETED"
                        
                        calculated_output = 1.0
                        
                        uncompleted_detail.start_time = start_time
                        uncompleted_detail.stop_time = stop_time
                        uncompleted_detail.job_operation = job_operation
                        uncompleted_detail.ct = ct
                        uncompleted_detail.pb = pb
                        uncompleted_detail.comment = merged_comment
                        uncompleted_detail.is_uncompleted = False
                        uncompleted_detail.output = calculated_output
                        uncompleted_detail.conn_no = conn_number  # ✅ SIMPAN CONNECTOR
                        uncompleted_detail.save()
                        
                        # Update jobDetail
                        try:
                            job_detail = jobDetail.objects.filter(
                                job=bjo,
                                remarks__icontains=f"{pin_or_box} threading for {joint_number}"
                            ).first()
                            
                            if job_detail:
                                if protector_type == 'pipe':
                                    job_detail.finished = Decimal('0.5')
                                else:
                                    job_detail.finished = Decimal('1.0')
                                
                                job_detail.remarks = job_detail.remarks.replace('UNCOMPLETED', 'COMPLETED')
                                job_detail.save()
                            elif protector_type != 'pipe':
                                auto_remarks = f"Auto: {pin_or_box} threading for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                                
                                jobDetail.objects.create(
                                    job=bjo,
                                    box=None,
                                    pin=None,
                                    fs=None,
                                    fc=None,
                                    finished=Decimal('1.0'),
                                    remarks=auto_remarks,
                                )
                        
                        except Exception as job_error:
                            print(f"Warning: Gagal mengupdate jobDetail: {str(job_error)}")
                        
                        if protector_type == 'box':
                            BoxProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        
                        # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if existing_connector:
                                # Update jika conn_number berbeda
                                if existing_connector.conn_number != conn_number:
                                    existing_connector.conn_number = conn_number
                                    existing_connector.save()
                            else:
                                # Create baru jika belum ada
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        qty_reduction_display = 0.25 if protector_type == 'pipe' else 0.5
                        tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                        
                        messages.success(
                            request, 
                            f"Threading UNCOMPLETED berhasil di-COMPLETE untuk joint '{joint_number}'{tag_info} (MERGED di header yang sama). "
                            f"Output: {calculated_output}. Job detail telah diupdate menjadi complete dengan finished +{qty_reduction_display}."
                        )
                        
                        return redirect('thread_detail', header_id=header.id)
                    
                    else:
                        # COMPLETION di header berbeda
                        old_uncompleted_comment = uncompleted_detail.comment or ''
                        
                        if comment:
                            merged_uncompleted_comment = f"COMPLETED | {comment}"
                            if old_uncompleted_comment and 'COMPLETED' not in old_uncompleted_comment:
                                merged_uncompleted_comment = f"{old_uncompleted_comment} | COMPLETED | {comment}"
                        else:
                            merged_uncompleted_comment = "COMPLETED"
                            if old_uncompleted_comment and 'COMPLETED' not in old_uncompleted_comment:
                                merged_uncompleted_comment = f"{old_uncompleted_comment} | COMPLETED"
                        
                        old_calculated_output = 0.5
                        
                        uncompleted_detail.comment = merged_uncompleted_comment
                        uncompleted_detail.is_uncompleted = False
                        uncompleted_detail.output = old_calculated_output
                        uncompleted_detail.save()
                        
                        new_calculated_output = 0.5
                        
                        if comment:
                            new_comment = f"COMPLETED | {comment}"
                        else:
                            new_comment = "COMPLETED"
                        
                        thread_detail = ThreadDetail.objects.create(
                            Reff=header,
                            start_time=start_time,
                            stop_time=stop_time,
                            bjo=bjo,
                            job_operation=job_operation,
                            pin_or_box=pin_or_box,
                            ct=ct,
                            pb=pb,
                            joint_number=joint_number,
                            is_uncompleted=False,
                            output=new_calculated_output,
                            comment=new_comment,
                            conn_no=conn_number,  # ✅ SIMPAN CONNECTOR
                        )
                        
                        # Create jobDetail baru
                        try:
                            if protector_type == 'pipe':
                                finished_value = Decimal('0.25')
                            else:
                                finished_value = Decimal('0.5')
                            
                            auto_remarks = f"Auto: {pin_or_box} threading COMPLETION for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} (from Header #{uncompleted_detail.Reff.id})"
                            if comment:
                                auto_remarks += f" | {comment}"
                            
                            job_detail = jobDetail.objects.create(
                                job=bjo,
                                box=None,
                                pin=None,
                                fs=None,
                                fc=None,
                                finished=finished_value,
                                remarks=auto_remarks,
                            )
                            
                        except Exception as job_error:
                            print(f"Warning: Gagal membuat jobDetail completion: {str(job_error)}")
                        
                        if protector_type == 'box':
                            BoxProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        
                        # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if existing_connector:
                                # Update jika conn_number berbeda
                                if existing_connector.conn_number != conn_number:
                                    existing_connector.conn_number = conn_number
                                    existing_connector.save()
                            else:
                                # Create baru jika belum ada
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        qty_reduction_display = 0.25 if protector_type == 'pipe' else 0.5
                        tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                        
                        messages.success(
                            request, 
                            f"Threading UNCOMPLETED berhasil di-COMPLETE untuk joint '{joint_number}'{tag_info} (BARU di header berbeda). "
                            f"Output record lama: {old_calculated_output}, Output record baru: {new_calculated_output}. "
                            f"Job detail created dengan finished +{qty_reduction_display}. "
                            f"Comment uncompleted di Header #{uncompleted_detail.Reff.id} telah diupdate dengan info completion."
                        )
                        
                        return redirect('thread_detail', header_id=header.id)

                # ========== PROSES REWORK MERGE ==========
                if is_merge_rework and rework_detail:
                    old_comment = rework_detail.comment or ''
                    
                    if comment:
                        merged_comment = f"REWORKED | {comment}"
                        if old_comment and not old_comment.startswith('REWORKED'):
                            merged_comment = f"{old_comment} | REWORKED | {comment}"
                    else:
                        merged_comment = "REWORKED"
                        if old_comment and not old_comment.startswith('REWORKED'):
                            merged_comment = f"{old_comment} | REWORKED"
                    
                    calculated_output = 1.0
                    
                    rework_detail.start_time = start_time
                    rework_detail.stop_time = stop_time
                    rework_detail.job_operation = job_operation
                    rework_detail.ct = ct
                    rework_detail.pb = pb
                    rework_detail.comment = merged_comment
                    rework_detail.output = calculated_output
                    rework_detail.conn_no = conn_number  # ✅ UPDATE CONNECTOR
                    rework_detail.save()
                    
                    if protector_type == 'box':
                        BoxProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=True)
                    elif protector_type == 'pin':
                        PinProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=True)
                    else:
                        SerialNumber.objects.filter(
                            joint_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=True)
                    
                    ThreadNcr.objects.filter(
                        serial=rework_detail,
                        reason__isnull=True
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    ThreadNcr.objects.filter(
                        serial=rework_detail,
                        reason__exact=''
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    ThreadNcr.objects.filter(
                        serial=rework_detail,
                        disposition__isnull=True
                    ).update(disposition="REWORK")
                    
                    ThreadNcr.objects.filter(
                        serial=rework_detail,
                        action__isnull=True
                    ).update(action="Threading rework performed")
                    ThreadNcr.objects.filter(
                        serial=rework_detail,
                        action__exact=''
                    ).update(action="Threading rework completed")
                    
                    # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                    if requires_connector and conn_number:
                        existing_connector = Connector.objects.filter(
                            bjo=bjo,
                            joint_number=joint_number
                        ).first()
                        
                        if existing_connector:
                            # Update jika conn_number berbeda
                            if existing_connector.conn_number != conn_number:
                                existing_connector.conn_number = conn_number
                                existing_connector.save()
                        else:
                            # Create baru jika belum ada
                            Connector.objects.create(
                                bjo=bjo,
                                joint_number=joint_number,
                                conn_number=conn_number
                            )
                    
                    tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                    
                    messages.success(
                        request, 
                        f"Threading detail REWORK berhasil di-merge dengan record existing untuk joint '{joint_number}'{tag_info}. "
                        f"Output: {calculated_output}. Status NCR telah diupdate menjadi complete."
                    )
                    
                else:
                    # ========== CREATE NEW THREAD DETAIL ==========
                    if is_rework:
                        if comment:
                            comment = f"REWORKED | {comment}"
                        else:
                            comment = "REWORKED"
                    elif is_uncompleted:
                        if comment:
                            comment = f"UNCOMPLETED | {comment}"
                        else:
                            comment = "UNCOMPLETED"
                    
                    calculated_output = 0.5 if is_uncompleted else 1.0
                    
                    thread_detail = ThreadDetail.objects.create(
                        Reff=header,
                        start_time=start_time,
                        stop_time=stop_time,
                        bjo=bjo,
                        job_operation=job_operation,
                        pin_or_box=pin_or_box,
                        ct=ct,
                        pb=pb,
                        joint_number=joint_number,
                        is_uncompleted=is_uncompleted,
                        output=calculated_output,
                        comment=comment if comment else None,
                        conn_no=conn_number,  # ✅ SIMPAN CONNECTOR
                    )

                    # Create jobDetail
                    if not is_rework:
                        if protector_type == 'pipe':
                            finished_value = Decimal('0.25') if is_uncompleted else Decimal('0.5')
                        else:
                            finished_value = Decimal('0.5') if is_uncompleted else Decimal('1.0')
                        
                        uncompleted_marker = " [UNCOMPLETED]" if is_uncompleted else ""
                        auto_remarks = f"Auto: {pin_or_box} threading for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}{uncompleted_marker}"
                        if comment and not comment.startswith('REWORKED') and not comment.startswith('UNCOMPLETED'):
                            auto_remarks += f" | {comment}"
                        
                        job_detail = jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_value,
                            remarks=auto_remarks,
                        )

                    if not is_rework and comment and 'NCR' in comment.upper():
                        try:
                            ThreadNcr.objects.create(
                                serial=thread_detail,
                            )
                            
                            if protector_type == 'box':
                                BoxProtector.objects.filter(
                                    serial_number=joint_number, 
                                    bjo=bjo
                                ).update(is_ncr=True)
                            elif protector_type == 'pin':
                                PinProtector.objects.filter(
                                    serial_number=joint_number, 
                                    bjo=bjo
                                ).update(is_ncr=True)
                            else:
                                SerialNumber.objects.filter(
                                    joint_number=joint_number, 
                                    bjo=bjo
                                ).update(is_ncr=True)
                            
                            # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                            if requires_connector and conn_number:
                                existing_connector = Connector.objects.filter(
                                    bjo=bjo,
                                    joint_number=joint_number
                                ).first()
                                
                                if existing_connector:
                                    # Update jika conn_number berbeda
                                    if existing_connector.conn_number != conn_number:
                                        existing_connector.conn_number = conn_number
                                        existing_connector.save()
                                else:
                                    # Create baru jika belum ada
                                    Connector.objects.create(
                                        bjo=bjo,
                                        joint_number=joint_number,
                                        conn_number=conn_number
                                    )
                            
                            uncompleted_status = " (UNCOMPLETED - output 0.5)" if is_uncompleted else ""
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                            
                            messages.warning(
                                request, 
                                f"Threading detail berhasil ditambahkan{uncompleted_status}{tag_info}. "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"NCR record telah dibuat untuk joint '{joint_number}'. "
                                "Silakan hubungi engineer untuk melengkapi detail NCR."
                            )
                            
                        except Exception as ncr_error:
                            uncompleted_status = " (UNCOMPLETED - output 0.5)" if is_uncompleted else ""
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                            
                            messages.warning(
                                request,
                                f"Threading detail berhasil ditambahkan{uncompleted_status}{tag_info}. "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"Namun gagal membuat NCR record: {str(ncr_error)}"
                            )
                            
                    elif is_rework and not is_merge_rework:
                        if protector_type == 'pipe':
                            other_detail = ThreadDetail.objects.filter(
                                joint_number=joint_number,
                                pin_or_box=pin_or_box,
                                bjo=bjo
                            ).exclude(Reff=header).first()
                            
                            if other_detail:
                                ThreadNcr.objects.filter(
                                    serial=other_detail,
                                    reason__isnull=True
                                ).update(reason="REWORKED in different header - Issue resolved")
                                
                                ThreadNcr.objects.filter(
                                    serial=other_detail,
                                    reason__exact=''
                                ).update(reason="REWORKED in different header - Issue resolved")
                        
                        # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if existing_connector:
                                # Update jika conn_number berbeda
                                if existing_connector.conn_number != conn_number:
                                    existing_connector.conn_number = conn_number
                                    existing_connector.save()
                            else:
                                # Create baru jika belum ada
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                        
                        messages.success(
                            request, 
                            f"Threading detail REWORK berhasil ditambahkan untuk joint '{joint_number}'{tag_info}. "
                            f"Output: {calculated_output}. Status NCR di header original telah diupdate."
                        )
                    else:
                        # ✅ CREATE/UPDATE CONNECTOR DENGAN VALIDASI
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if existing_connector:
                                # Update jika conn_number berbeda
                                if existing_connector.conn_number != conn_number:
                                    existing_connector.conn_number = conn_number
                                    existing_connector.save()
                            else:
                                # Create baru jika belum ada
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        if is_uncompleted:
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                            
                            messages.warning(
                                request, 
                                f"Threading detail UNCOMPLETED berhasil ditambahkan (output 0.5){tag_info}. "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"Item ini masih bisa diselect lagi untuk melengkapinya."
                            )
                        else:
                            tag_info = f" (Info Tag: {info_tag_display})" if info_tag_display else ""
                            
                            messages.success(
                                request, 
                                f"Threading detail berhasil ditambahkan{tag_info}. "
                                f"Job detail otomatis dibuat dengan finished={finished_value}. Output: {calculated_output}."
                            )

                    # ===== UPDATE SerialNumber UNTUK PIPE (NORMAL UPDATE) =====
                    if not is_rework and not is_uncompleted:
                        if protector_type == 'box':
                            BoxProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_threaded=True)
                        elif protector_type == 'pipe':
                            if pin_or_box == 'BOX':
                                SerialNumber.objects.filter(
                                    joint_number=joint_number,
                                    bjo=bjo
                                ).update(is_box_threaded=True)
                            elif pin_or_box == 'PIN':
                                SerialNumber.objects.filter(
                                    joint_number=joint_number,
                                    bjo=bjo
                                ).update(is_pin_threaded=True)

                return redirect('thread_detail', header_id=header.id)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('thread_detail', header_id=header.id)

    # ========== GET METHOD - TAMPILKAN DATA ==========
    detail_list = ThreadDetail.objects.filter(Reff=header).order_by('id')
    for detail in detail_list:
        detail.duration_minutes = calculate_time_duration(detail.start_time, detail.stop_time)
        
        if detail.joint_number:
            if BoxProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists():
                detail.joint_type = 'box_protector'
                detail.joint_type_display = 'BOX Protector'
                detail.joint_type_class = 'text-info'
                
                box_protector = BoxProtector.objects.filter(
                    serial_number=detail.joint_number, 
                    bjo=detail.bjo
                ).first()
                detail.is_rework = box_protector.is_rwk if box_protector else False
                
            elif PinProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists():
                detail.joint_type = 'pin_protector'
                detail.joint_type_display = 'PIN Protector'
                detail.joint_type_class = 'text-primary'
                
                pin_protector = PinProtector.objects.filter(
                    serial_number=detail.joint_number, 
                    bjo=detail.bjo
                ).first()
                detail.is_rework = pin_protector.is_rwk if pin_protector else False
                
            else:
                detail.joint_type = 'pipe'
                
                info_tag_name = detail.bjo.info.name.upper() if detail.bjo.info else ''
                is_bxb = 'B X B' in info_tag_name or 'BXB' in info_tag_name
                is_pxp = 'P X P' in info_tag_name or 'PXP' in info_tag_name
                
                if is_bxb:
                    detail.joint_type_display = 'PIPE Joint (B X B)'
                    detail.joint_type_class = 'text-warning'
                elif is_pxp:
                    detail.joint_type_display = 'PIPE Joint (P X P)'
                    detail.joint_type_class = 'text-warning'
                else:
                    detail.joint_type_display = 'PIPE Joint'
                    detail.joint_type_class = 'text-success'
                
                serial = SerialNumber.objects.filter(
                    joint_number=detail.joint_number, 
                    bjo=detail.bjo
                ).first()
                detail.is_rework = serial.is_rwk if serial else False
        else:
            detail.joint_type = 'unknown'
            detail.joint_type_display = 'Unknown'
            detail.joint_type_class = 'text-muted'
            detail.is_rework = False
        
        try:
            detail.ncr_count = ThreadNcr.objects.filter(serial=detail).count()
            detail.has_ncr = detail.ncr_count > 0
            
            detail.has_incomplete_ncr = ThreadNcr.objects.filter(
                serial=detail,
                reason__isnull=True
            ).exists() or ThreadNcr.objects.filter(
                serial=detail,
                reason__exact=''
            ).exists()
            
        except:
            detail.ncr_count = 0
            detail.has_ncr = False
            detail.has_incomplete_ncr = False

    existing_consumable = ThreadConsumsion.objects.filter(Reff=header).first()

    def detect_bjo_type(bjo):
        bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
        product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        if bjo_for:
            if 'BOX' in bjo_for:
                return 'box'
            elif 'PIN' in bjo_for:
                return 'pin'
            elif 'PIPE' in bjo_for or 'THREADING' in bjo_for:
                return 'pipe'
        
        if product and not bjo_for:
            if 'BOX' in product:
                return 'box'
            elif 'PIN' in product:
                return 'pin'
        
        if process_name and not bjo_for and not product:
            if 'BOX' in process_name:
                return 'box'
            elif 'PIN' in process_name:
                return 'pin'
        
        return 'pipe'

    job_list = []
    for job in JobHeader.objects.filter(is_finish__in=[False, None]).order_by('bjo'):
        job_bjo_type = detect_bjo_type(job)
        
        if job_bjo_type == 'pipe':
            min_required_qty = 0.25
        else:
            min_required_qty = 0.5
        
        from decimal import Decimal
        total_finished = jobDetail.objects.filter(job=job).aggregate(
            total=Sum('finished')
        )['total'] or Decimal(0)
        remaining_qty = float(job.qty) - float(total_finished)
        
        if remaining_qty >= min_required_qty:
            job_list.append(job)

    detail_count = detail_list.count()

    context = {
        'header': header,
        'detail_list': detail_list,
        'job_list': job_list,
        'detail_count': detail_count,
        'existing_consumable': existing_consumable,
    }
    return render(request, 'thread/detail.html', context)

@threading_write_access_required
def handle_update_consumable(request, header):
    """Handle update consumable data - dengan auto revert untuk posted records"""
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit consumable data on posted records.'
            )
            return redirect('thread_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan consumable."
            )
    
    try:
        # Ambil data consumable dari form
        insert_snmg = request.POST.get("insert_snmg", 0)
        insert_dnmg = request.POST.get("insert_dnmg", 0)
        insert_threading = request.POST.get("insert_threading", 0)
        consumable_others = request.POST.get("consumable_others", 0)

        # Cek apakah sudah ada record consumable untuk header ini
        existing_consumable = ThreadConsumsion.objects.filter(Reff=header).first()

        # Prepare data untuk save
        consumable_data = {
            'insert_snmg': float(insert_snmg or 0),
            'insert_dnmg': float(insert_dnmg or 0),
            'insert_threading': float(insert_threading or 0),
            'others': float(consumable_others or 0),
        }

        if existing_consumable:
            # Update existing record
            for key, value in consumable_data.items():
                setattr(existing_consumable, key, value)
            existing_consumable.save()
            messages.success(request, "Data consumable berhasil diupdate.")
        else:
            # Create new record
            consumable_data['Reff'] = header
            ThreadConsumsion.objects.create(**consumable_data)
            messages.success(request, "Data consumable berhasil disimpan.")

        return redirect('thread_detail', header_id=header.id)

    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menyimpan data consumable: {str(e)}")
        return redirect('thread_detail', header_id=header.id)


def get_joint_numbers(request):
    bjo_id = request.GET.get('bjo_id')
    
    if not bjo_id:
        return JsonResponse({'joint_numbers': []})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        joint_list = []
        
        # ===== CEK INFO TAG - HANYA UNTUK DISPLAY =====
        info_tag_name = bjo.info.name.upper() if bjo.info else ''
        is_bxb = 'B X B' in info_tag_name or 'BXB' in info_tag_name
        is_pxp = 'P X P' in info_tag_name or 'PXP' in info_tag_name
        
        info_tag_display = None
        if is_bxb:
            info_tag_display = 'B X B'
        elif is_pxp:
            info_tag_display = 'P X P'
        
        # Fungsi deteksi jenis BJO
        def detect_bjo_type(bjo):
            bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
            product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
            process_name = bjo.process_type.name.upper() if bjo.process_type else ''
            
            if bjo_for:
                if 'BOX' in bjo_for:
                    return 'box'
                elif 'PIN' in bjo_for:
                    return 'pin'
                elif 'PIPE' in bjo_for or 'THREADING' in bjo_for:
                    return 'pipe'
            
            if product and not bjo_for:
                if 'BOX' in product:
                    return 'box'
                elif 'PIN' in product:
                    return 'pin'
            
            if process_name and not bjo_for and not product:
                if 'BOX' in process_name:
                    return 'box'
                elif 'PIN' in process_name:
                    return 'pin'
            
            return 'pipe'

        bjo_type = detect_bjo_type(bjo)
        
        if bjo_type == 'box':
            # ===== BOX PROTECTOR LOGIC =====
            protectors = BoxProtector.objects.filter(bjo=bjo).filter(
                Q(is_threaded=False) | 
                (Q(is_threaded=True) & Q(is_rwk=False))
            ).order_by('serial_number')
            
            uncompleted_protectors_list = []
            all_uncompleted = ThreadDetail.objects.filter(
                bjo=bjo,
                pin_or_box='BOX',
                is_uncompleted=True
            ).values_list('joint_number', flat=True).distinct()
            
            for joint_num in all_uncompleted:
                has_completed = ThreadDetail.objects.filter(
                    joint_number=joint_num,
                    bjo=bjo,
                    pin_or_box='BOX',
                    is_uncompleted=False
                ).exists()
                
                if not has_completed:
                    uncompleted_protectors_list.append(joint_num)
            
            uncompleted_protector_numbers = uncompleted_protectors_list
            
            for protector in protectors:
                status = 'normal'
                
                if protector.serial_number in uncompleted_protector_numbers:
                    status = 'uncompleted'
                
                elif protector.is_threaded and not protector.is_rwk:
                    existing_detail = ThreadDetail.objects.filter(
                        joint_number=protector.serial_number,
                        bjo=bjo,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).first()
                    
                    if existing_detail:
                        has_ncr = ThreadNcr.objects.filter(serial=existing_detail).exists()
                        
                        if has_ncr:
                            status = 'rework'
                        else:
                            continue
                    else:
                        continue
                
                elif not protector.is_threaded:
                    status = 'normal'
                elif protector.is_rwk:
                    continue
                
                joint_list.append({
                    'joint_number': protector.serial_number,
                    'options': ['BOX'],
                    'type': 'box_protector',
                    'status': status,
                    'is_rework': status == 'rework',
                    'is_uncompleted': status == 'uncompleted',
                    'info_tag': info_tag_display,
                    'rework_info': {
                        'is_ncr': protector.is_ncr,
                        'is_rwk': protector.is_rwk,
                        'is_threaded': protector.is_threaded
                    }
                })
            
            for uncompleted_joint in uncompleted_protector_numbers:
                if not any(j['joint_number'] == uncompleted_joint for j in joint_list):
                    protector = BoxProtector.objects.filter(serial_number=uncompleted_joint, bjo=bjo).first()
                    if protector:
                        joint_list.append({
                            'joint_number': protector.serial_number,
                            'options': ['BOX'],
                            'type': 'box_protector',
                            'status': 'uncompleted',
                            'is_rework': False,
                            'is_uncompleted': True,
                            'info_tag': info_tag_display,
                            'rework_info': {
                                'is_ncr': protector.is_ncr,
                                'is_rwk': protector.is_rwk,
                                'is_threaded': protector.is_threaded
                            }
                        })
                    
        elif bjo_type == 'pin':
            # ===== PIN PROTECTOR LOGIC =====
            protectors = PinProtector.objects.filter(bjo=bjo).filter(
                Q(is_threaded=False) | 
                (Q(is_threaded=True) & Q(is_rwk=False))
            ).order_by('serial_number')
            
            uncompleted_protectors_list = []
            all_uncompleted = ThreadDetail.objects.filter(
                bjo=bjo,
                pin_or_box='PIN',
                is_uncompleted=True
            ).values_list('joint_number', flat=True).distinct()
            
            for joint_num in all_uncompleted:
                has_completed = ThreadDetail.objects.filter(
                    joint_number=joint_num,
                    bjo=bjo,
                    pin_or_box='PIN',
                    is_uncompleted=False
                ).exists()
                
                if not has_completed:
                    uncompleted_protectors_list.append(joint_num)
            
            uncompleted_protector_numbers = uncompleted_protectors_list
            
            for protector in protectors:
                status = 'normal'
                
                if protector.serial_number in uncompleted_protector_numbers:
                    status = 'uncompleted'
                
                elif protector.is_threaded and not protector.is_rwk:
                    existing_detail = ThreadDetail.objects.filter(
                        joint_number=protector.serial_number,
                        bjo=bjo,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).first()
                    
                    if existing_detail:
                        has_ncr = ThreadNcr.objects.filter(serial=existing_detail).exists()
                        
                        if has_ncr:
                            status = 'rework'
                        else:
                            continue
                    else:
                        continue
                
                elif not protector.is_threaded:
                    status = 'normal'
                elif protector.is_rwk:
                    continue
                
                joint_list.append({
                    'joint_number': protector.serial_number,
                    'options': ['PIN'],
                    'type': 'pin_protector',
                    'status': status,
                    'is_rework': status == 'rework',
                    'is_uncompleted': status == 'uncompleted',
                    'info_tag': info_tag_display,
                    'rework_info': {
                        'is_ncr': protector.is_ncr,
                        'is_rwk': protector.is_rwk,
                        'is_threaded': protector.is_threaded
                    }
                })
            
            for uncompleted_joint in uncompleted_protector_numbers:
                if not any(j['joint_number'] == uncompleted_joint for j in joint_list):
                    protector = PinProtector.objects.filter(serial_number=uncompleted_joint, bjo=bjo).first()
                    if protector:
                        joint_list.append({
                            'joint_number': protector.serial_number,
                            'options': ['PIN'],
                            'type': 'pin_protector',
                            'status': 'uncompleted',
                            'is_rework': False,
                            'is_uncompleted': True,
                            'info_tag': info_tag_display,
                            'rework_info': {
                                'is_ncr': protector.is_ncr,
                                'is_rwk': protector.is_rwk,
                                'is_threaded': protector.is_threaded
                            }
                        })
        
        else:  # PIPE BJO
            # ===== PIPE LOGIC WITH DEBUG =====
            serials = SerialNumber.objects.filter(bjo=bjo).order_by('joint_number')
            
            print(f"\n{'='*60}")
            print(f"DEBUG: get_joint_numbers for BJO {bjo.bjo} (ID: {bjo.id})")
            print(f"Total SerialNumbers found: {serials.count()}")
            print(f"{'='*60}\n")

            for serial in serials:
                print(f"--- Processing Joint: {serial.joint_number} ---")
                
                # CEK STATUS THREADING PER SISI
                pin_any_threading = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='PIN', 
                    bjo=bjo
                ).exists()
                
                box_any_threading = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='BOX', 
                    bjo=bjo
                ).exists()
                
                print(f"  PIN any threading: {pin_any_threading}")
                print(f"  BOX any threading: {box_any_threading}")

                # CEK STATUS UNCOMPLETED PER SISI
                pin_has_uncompleted = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='PIN', 
                    bjo=bjo,
                    is_uncompleted=True
                ).exists()
                
                pin_has_completed = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='PIN', 
                    bjo=bjo,
                    is_uncompleted=False
                ).exists()
                
                pin_uncompleted = pin_has_uncompleted and not pin_has_completed

                box_has_uncompleted = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='BOX', 
                    bjo=bjo,
                    is_uncompleted=True
                ).exists()
                
                box_has_completed = ThreadDetail.objects.filter(
                    joint_number=serial.joint_number, 
                    pin_or_box='BOX', 
                    bjo=bjo,
                    is_uncompleted=False
                ).exists()
                
                box_uncompleted = box_has_uncompleted and not box_has_completed
                
                print(f"  PIN - has_uncompleted: {pin_has_uncompleted}, has_completed: {pin_has_completed}, uncompleted: {pin_uncompleted}")
                print(f"  BOX - has_uncompleted: {box_has_uncompleted}, has_completed: {box_has_completed}, uncompleted: {box_uncompleted}")

                options = []
                rework_options = []
                uncompleted_options = []
                
                # ===== NORMAL THREADING =====
                if not pin_any_threading:
                    options.append('PIN')
                    print(f"  ✓ Added PIN to normal options (no threading exists)")
                if not box_any_threading:
                    options.append('BOX')
                    print(f"  ✓ Added BOX to normal options (no threading exists)")
                
                # ===== REWORK LOGIC =====
                if pin_has_completed:
                    pin_details = ThreadDetail.objects.filter(
                        joint_number=serial.joint_number, 
                        pin_or_box='PIN',
                        bjo=bjo,
                        is_uncompleted=False
                    )
                    is_already_reworked = any('REWORKED' in (d.comment or '') for d in pin_details)
                    latest_pin_detail = pin_details.order_by('-id').first()
                    has_ncr = ThreadNcr.objects.filter(serial=latest_pin_detail).exists() if latest_pin_detail else False
                    
                    print(f"  PIN - is_already_reworked: {is_already_reworked}, has_ncr: {has_ncr}")
                    
                    if has_ncr and not is_already_reworked and 'PIN' not in options:
                        rework_options.append('PIN')
                        print(f"  ✓ Added PIN to rework_options (has NCR, not yet reworked)")
                        
                if box_has_completed:
                    box_details = ThreadDetail.objects.filter(
                        joint_number=serial.joint_number, 
                        pin_or_box='BOX',
                        bjo=bjo,
                        is_uncompleted=False
                    )
                    
                    is_already_reworked = any('REWORKED' in (d.comment or '') for d in box_details)
                    latest_box_detail = box_details.order_by('-id').first()
                    has_ncr = ThreadNcr.objects.filter(serial=latest_box_detail).exists() if latest_box_detail else False
                    
                    print(f"  BOX - is_already_reworked: {is_already_reworked}, has_ncr: {has_ncr}")
                    
                    if has_ncr and not is_already_reworked and 'BOX' not in options:
                        rework_options.append('BOX')
                        print(f"  ✓ Added BOX to rework_options (has NCR, not yet reworked)")

                # ===== UNCOMPLETED COMPLETION LOGIC =====
                if pin_uncompleted and 'PIN' not in options and 'PIN' not in rework_options:
                    uncompleted_options.append('PIN')
                    print(f"  ✓ Added PIN to uncompleted_options (has uncompleted, no completed yet)")
                if box_uncompleted and 'BOX' not in options and 'BOX' not in rework_options:
                    uncompleted_options.append('BOX')
                    print(f"  ✓ Added BOX to uncompleted_options (has uncompleted, no completed yet)")

                # ===== GABUNGKAN SEMUA OPTIONS =====
                all_options = options + rework_options + uncompleted_options
                
                print(f"  FINAL OPTIONS:")
                print(f"    - normal: {options}")
                print(f"    - rework: {rework_options}")
                print(f"    - uncompleted: {uncompleted_options}")
                print(f"    - ALL: {all_options}")
                print(f"  Will be added to joint_list: {len(all_options) > 0}")

                if all_options:
                    has_rework = len(rework_options) > 0
                    has_uncompleted = pin_uncompleted or box_uncompleted
                    
                    if has_uncompleted:
                        status = 'uncompleted'
                    elif has_rework:
                        status = 'rework'
                    else:
                        status = 'normal'
                    
                    if is_bxb:
                        type_display = 'pipe_bxb'
                    elif is_pxp:
                        type_display = 'pipe_pxp'
                    else:
                        type_display = 'pipe'
                    
                    joint_list.append({
                        'joint_number': serial.joint_number,
                        'options': all_options,
                        'type': type_display,
                        'status': status,
                        'is_rework': has_rework,
                        'is_uncompleted': has_uncompleted,
                        'info_tag': info_tag_display,
                        'rework_info': {
                            'is_ncr': serial.is_ncr,
                            'is_rwk': serial.is_rwk,
                            'pin_any_threading': pin_any_threading,
                            'box_any_threading': box_any_threading,
                            'pin_has_completed': pin_has_completed,
                            'box_has_completed': box_has_completed,
                            'pin_uncompleted': pin_uncompleted,
                            'box_uncompleted': box_uncompleted,
                            'normal_options': options,
                            'rework_options': rework_options,
                            'uncompleted_options': uncompleted_options
                        }
                    })
                    print(f"  ✓✓✓ Added to joint_list with status: {status}")
                else:
                    print(f"  ✗✗✗ NOT added to joint_list (no options available)")
                
                print()  # Empty line for readability
            
            print(f"{'='*60}")
            print(f"FINAL RESULT: {len(joint_list)} joints added to joint_list")
            print(f"{'='*60}\n")

        return JsonResponse({'joint_numbers': joint_list})

    except JobHeader.DoesNotExist:
        return JsonResponse({'joint_numbers': []})
    except Exception as e:
        print(f"ERROR in get_joint_numbers: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'joint_numbers': [], 'error': str(e)})


def get_ct_pb_values(request):
    """AJAX untuk mengambil nilai CT dan PB berdasarkan BJO yang dipilih"""
    bjo_id = request.GET.get('bjo_id')
    if not bjo_id:
        return JsonResponse({'ct': None, 'pb': None})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        
        # Ambil CT dari tabel CycleTime
        ct_value = None
        pb_value = None
        
        if bjo.size and bjo.ct_reference and bjo.process_type:
            try:
                cycle_time = CycleTime.objects.get(
                    process_type=bjo.process_type,
                    od_thickness=bjo.size,
                    ct_for=bjo.ct_reference
                )
                ct_value = float(cycle_time.hours) if cycle_time.hours else None
            except CycleTime.DoesNotExist:
                pass
        
        # Ambil PB dari tabel PriceBook
        if bjo.size and bjo.ct_reference and bjo.process_type:
            try:
                price_book = PriceBook.objects.get(
                    process_type=bjo.process_type,
                    od_thickness=bjo.size,
                    pb_for=bjo.ct_reference
                )
                pb_value = float(price_book.time_in_h) if price_book.time_in_h else None
            except PriceBook.DoesNotExist:
                pass

        return JsonResponse({
            'ct': ct_value,
            'pb': pb_value,
            'bjo_info': {
                'size': str(bjo.size) if bjo.size else None,
                'grade': str(bjo.ct_reference) if bjo.ct_reference else None,
                'process': str(bjo.process_type) if bjo.process_type else None
            }
        })

    except JobHeader.DoesNotExist:
        return JsonResponse({'ct': None, 'pb': None})


def calculate_time_duration(start_time, stop_time):
    """
    Fungsi untuk menghitung durasi waktu dengan mempertimbangkan:
    1. Cross-midnight shift
    2. Lunch break (dikurangi 1 jam jika melewati jam 12:00 PM atau 12:00 AM)
    
    FIXED VERSION - menangani cross-midnight dengan benar
    """
    if not start_time or not stop_time:
        return None
    
    start_minutes = start_time.hour * 60 + start_time.minute
    stop_minutes = stop_time.hour * 60 + stop_time.minute
    
    # Simpan nilai original untuk pengecekan lunch break
    original_start_minutes = start_minutes
    original_stop_minutes = stop_minutes
    
    # Handle case jika melewati midnight (00:00)
    is_cross_midnight = stop_minutes < start_minutes
    if is_cross_midnight:
        stop_minutes += 24 * 60
    
    duration_minutes = stop_minutes - start_minutes
    
    # Cek apakah melewati jam makan (lunch break)
    crossed_lunch = False
    
    # Case 1: Shift normal (tidak melewati midnight)
    if not is_cross_midnight:
        # Melewati 12:00 PM (720 menit)
        if original_start_minutes < 720 and original_stop_minutes >= 720:
            crossed_lunch = True
    else:
        # Case 2: Shift melewati midnight
        # Bisa melewati 12:00 PM (jika start sebelum 12:00 PM)
        if original_start_minutes < 720:  # Start sebelum 12:00 PM
            crossed_lunch = True
        # ATAU melewati 12:00 AM (midnight) - selalu true untuk cross-midnight shift
        else:
            crossed_lunch = True
    
    # Kurangi 1 jam (60 menit) jika melewati jam makan
    if crossed_lunch:
        duration_minutes -= 60
        
    # Pastikan duration tidak negatif dan konversi ke jam
    duration_minutes = max(0, duration_minutes)
    return round(duration_minutes / 60, 2)  # Konversi ke jam dengan 2 desimal

@threading_detail_edit_access_required
def handle_edit_thread_detail(request, header_id):
    """Handle edit threading detail with NCR auto-creation/deletion and UNCOMPLETED toggle"""
    header = get_object_or_404(ThreadHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit details on posted records.'
            )
            return redirect('thread_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan detail."
            )
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    
    try:
        detail = ThreadDetail.objects.get(id=detail_id, Reff=header)
        old_comment = detail.comment or ''
        old_is_uncompleted = detail.is_uncompleted
        old_output = detail.output
        old_conn_no = detail.conn_no  # ✅ SIMPAN CONN_NO LAMA
    except ThreadDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    
    try:
        # Validasi waktu
        start_time_str = request.POST.get('start_time')
        stop_time_str = request.POST.get('stop_time')
        
        if not start_time_str or not stop_time_str:
            messages.error(request, "Start Time dan Stop Time wajib diisi.")
            return redirect('thread_detail', header_id=header.id)
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format waktu tidak valid.")
            return redirect('thread_detail', header_id=header.id)
        
        # Validasi waktu dengan support untuk shift cross-midnight
        start_minutes = start_time.hour * 60 + start_time.minute
        stop_minutes = stop_time.hour * 60 + stop_time.minute

        if start_time == stop_time:
            messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
            return redirect('thread_detail', header_id=header.id)

        if stop_minutes < start_minutes:
            duration = (stop_minutes + 24 * 60) - start_minutes
        else:
            duration = stop_minutes - start_minutes

        if duration > 24 * 60:
            messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
            return redirect('thread_detail', header_id=header.id)
        
        # Validasi Job Operation
        job_operation = request.POST.get('job_operation', '').strip()
        if not job_operation:
            messages.error(request, "Job Operation wajib diisi.")
            return redirect('thread_detail', header_id=header.id)
        
        if len(job_operation) > 3:
            messages.error(request, "Job Operation maksimal 3 karakter.")
            return redirect('thread_detail', header_id=header.id)
        
        # Handle CT
        ct = None
        ct_str = request.POST.get('ct')
        if ct_str:
            try:
                ct = float(ct_str)
                if ct < 0:
                    messages.error(request, "CT tidak boleh negatif.")
                    return redirect('thread_detail', header_id=header.id)
            except ValueError:
                messages.error(request, "CT harus berupa angka.")
                return redirect('thread_detail', header_id=header.id)
        
        # Handle PB
        pb = None
        pb_str = request.POST.get('pb')
        if pb_str:
            try:
                pb = float(pb_str)
                if pb < 0:
                    messages.error(request, "PB tidak boleh negatif.")
                    return redirect('thread_detail', header_id=header.id)
            except ValueError:
                messages.error(request, "PB harus berupa angka.")
                return redirect('thread_detail', header_id=header.id)
        
        # ===== HANDLE UNCOMPLETED STATUS TOGGLE =====
        toggle_status = request.POST.get('toggle_status')
        
        if toggle_status is not None:
            # User mengubah status via toggle
            new_is_uncompleted = request.POST.get('is_uncompleted') == 'on'
        else:
            # User hanya edit field lain, pertahankan status lama
            new_is_uncompleted = old_is_uncompleted
        
        # Handle Comment
        comment = request.POST.get('comment', '').strip()
        
        # ✅ HANDLE CONNECTOR NUMBER EDIT
        bjo = detail.bjo
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        # Cek apakah BJO ini memerlukan connector
        requires_connector = False
        if 'THREAD' in process_name:
            conn_name = bjo.conn.name.upper() if bjo.conn else ''
            valid_connections = ['XLW-S', 'XLW-GT', 'XLW']
            requires_connector = any(vc in conn_name for vc in valid_connections)
        
        if requires_connector:
            conn_number_raw = request.POST.get('conn_number', '')
            conn_number = clean_conn_number(conn_number_raw) if conn_number_raw else None
            
            if not conn_number:
                messages.error(request, "Connector Number wajib diisi untuk BJO dengan connection XLW-S, XLW-GT, atau XLW.")
                return redirect('thread_detail', header_id=header.id)
            
            # ✅ VALIDASI BARU: conn_number harus unique, KECUALI untuk BJO + Joint Number yang sama
            existing_conn = Connector.objects.filter(conn_number=conn_number).exclude(
                bjo=bjo,
                joint_number=detail.joint_number
            ).first()

            if existing_conn:
                messages.error(
                    request,
                    f"Connector Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                    f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
                )
                return redirect('thread_detail', header_id=header.id)
        else:
            conn_number = None
        
        # ✅ INITIALIZE calculated_output dengan nilai lama terlebih dahulu
        calculated_output = old_output
        
        # ===== HANDLE PERUBAHAN STATUS UNCOMPLETED =====
        if old_is_uncompleted != new_is_uncompleted:
            # ✅ HANYA RECALCULATE OUTPUT JIKA ADA PERUBAHAN STATUS
            calculated_output = 0.5 if new_is_uncompleted else 1.0
            
            # Deteksi jenis protector
            is_box_protector = BoxProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
            is_pin_protector = PinProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
            is_pipe = not is_box_protector and not is_pin_protector
            
            bjo.refresh_from_db()
            
            from decimal import Decimal
            
            if new_is_uncompleted and not old_is_uncompleted:
                # ===== COMPLETE → UNCOMPLETED =====
                if is_pipe:
                    qty_adjustment = 0.25
                    finished_old = Decimal('0.5')
                    finished_new = Decimal('0.25')
                else:
                    qty_adjustment = 0.5
                    finished_old = Decimal('0.5')
                    finished_new = None
                
                bjo.qty = float(bjo.qty) + qty_adjustment
                bjo.save()
                
                job_detail = jobDetail.objects.filter(
                    job=bjo,
                    remarks__icontains=f"{detail.pin_or_box} threading for {detail.joint_number}",
                    finished=finished_old
                ).first()
                
                if job_detail:
                    if is_pipe:
                        job_detail.finished = finished_new
                        if '[UNCOMPLETED]' not in job_detail.remarks:
                            job_detail.remarks = job_detail.remarks.replace('[COMPLETED]', '').strip()
                            job_detail.remarks += " [UNCOMPLETED]"
                        job_detail.save()
                    else:
                        job_detail.delete()
                
                old_comment_clean = old_comment.replace('COMPLETED |', '').replace('| COMPLETED', '').strip()
                if comment:
                    comment = f"UNCOMPLETED | {comment}"
                else:
                    if old_comment_clean:
                        comment = f"UNCOMPLETED | {old_comment_clean}"
                    else:
                        comment = "UNCOMPLETED"
                
                messages.info(request, f"Status berubah menjadi UNCOMPLETED. Quantity dikembalikan +{qty_adjustment}")
                
            elif not new_is_uncompleted and old_is_uncompleted:
                # ===== UNCOMPLETED → COMPLETE =====
                existing_uncompleted_same_header = ThreadDetail.objects.filter(
                    Reff=header,
                    joint_number=detail.joint_number,
                    bjo=bjo,
                    pin_or_box=detail.pin_or_box,
                    is_uncompleted=True
                ).exclude(id=detail.id).first()
                
                if existing_uncompleted_same_header:
                    # MERGE KE RECORD UNCOMPLETED
                    old_uncompleted_comment = existing_uncompleted_same_header.comment or ''
                    
                    if comment:
                        merged_comment = f"COMPLETED | {comment}"
                        if old_uncompleted_comment and not old_uncompleted_comment.startswith('COMPLETED'):
                            merged_comment = f"{old_uncompleted_comment} | COMPLETED | {comment}"
                    else:
                        merged_comment = "COMPLETED"
                        if old_uncompleted_comment:
                            merged_comment = f"{old_uncompleted_comment} | COMPLETED"
                    
                    calculated_output = 1.0
                    
                    existing_uncompleted_same_header.start_time = start_time
                    existing_uncompleted_same_header.stop_time = stop_time
                    existing_uncompleted_same_header.job_operation = job_operation
                    existing_uncompleted_same_header.ct = ct
                    existing_uncompleted_same_header.pb = pb
                    existing_uncompleted_same_header.comment = merged_comment
                    existing_uncompleted_same_header.is_uncompleted = False
                    existing_uncompleted_same_header.output = calculated_output
                    existing_uncompleted_same_header.conn_no = conn_number  # ✅ UPDATE CONNECTOR
                    existing_uncompleted_same_header.save()
                    
                    detail.delete()
                    
                    if is_pipe:
                        qty_adjustment = 0.25
                        finished_old = Decimal('0.25')
                        finished_new = Decimal('0.5')
                    else:
                        qty_adjustment = 0.5
                        finished_old = None
                        finished_new = Decimal('0.5')
                    
                    bjo.qty = float(bjo.qty) - qty_adjustment
                    if bjo.qty < 0:
                        bjo.qty = 0
                    bjo.save()
                    
                    if is_pipe:
                        job_detail = jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=f"{detail.pin_or_box} threading for {detail.joint_number}",
                            finished=finished_old
                        ).first()
                        
                        if job_detail:
                            job_detail.finished = finished_new
                            job_detail.remarks = job_detail.remarks.replace('[UNCOMPLETED]', '[COMPLETED]')
                            job_detail.save()
                    else:
                        auto_remarks = f"Auto: {detail.pin_or_box} threading for {detail.joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_new,
                            remarks=auto_remarks,
                        )
                    
                    if is_box_protector:
                        BoxProtector.objects.filter(
                            serial_number=detail.joint_number,
                            bjo=bjo
                        ).update(is_threaded=True)
                    elif is_pin_protector:
                        PinProtector.objects.filter(
                            serial_number=detail.joint_number,
                            bjo=bjo
                        ).update(is_threaded=True)
                    
                    # ✅ UPDATE CONNECTOR DENGAN VALIDASI
                    if requires_connector and conn_number:
                        existing_connector = Connector.objects.filter(
                            bjo=bjo,
                            joint_number=detail.joint_number
                        ).first()
                        
                        if existing_connector:
                            # Update jika conn_number berbeda
                            if existing_connector.conn_number != conn_number:
                                existing_connector.conn_number = conn_number
                                existing_connector.save()
                        else:
                            # Create baru jika belum ada
                            Connector.objects.create(
                                bjo=bjo,
                                joint_number=detail.joint_number,
                                conn_number=conn_number
                            )
                    
                    messages.success(
                        request,
                        f"Threading UNCOMPLETED berhasil di-COMPLETE dan di-merge dengan record existing. "
                        f"Output: {calculated_output}. Quantity dikurangi -{qty_adjustment}"
                    )
                    
                    return redirect('thread_detail', header_id=header.id)
                    
                else:
                    # UPDATE BIASA (BEDA HEADER)
                    if is_pipe:
                        qty_adjustment = 0.25
                        finished_old = Decimal('0.25')
                        finished_new = Decimal('0.5')
                    else:
                        qty_adjustment = 0.5
                        finished_old = None
                        finished_new = Decimal('0.5')
                    
                    bjo.qty = float(bjo.qty) - qty_adjustment
                    if bjo.qty < 0:
                        bjo.qty = 0
                    bjo.save()
                    
                    if is_pipe:
                        job_detail = jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=f"{detail.pin_or_box} threading for {detail.joint_number}",
                            finished=finished_old
                        ).first()
                        
                        if job_detail:
                            job_detail.finished = finished_new
                            job_detail.remarks = job_detail.remarks.replace('[UNCOMPLETED]', '[COMPLETED]')
                            job_detail.save()
                    else:
                        auto_remarks = f"Auto: {detail.pin_or_box} threading for {detail.joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_new,
                            remarks=auto_remarks,
                        )
                    
                    if is_box_protector:
                        BoxProtector.objects.filter(
                            serial_number=detail.joint_number,
                            bjo=bjo
                        ).update(is_threaded=True)
                    elif is_pin_protector:
                        PinProtector.objects.filter(
                            serial_number=detail.joint_number,
                            bjo=bjo
                        ).update(is_threaded=True)
                    
                    old_comment_clean = old_comment.replace('UNCOMPLETED |', '').replace('| UNCOMPLETED', '').strip()
                    if comment:
                        comment = f"COMPLETED | {comment}"
                    else:
                        if old_comment_clean:
                            comment = f"COMPLETED | {old_comment_clean}"
                        else:
                            comment = "COMPLETED"
                    
                    messages.info(request, f"Status berubah menjadi COMPLETE. Quantity dikurangi -{qty_adjustment}")
        
        # ✅ OUTPUT HANYA BERUBAH JIKA ADA PERUBAHAN STATUS UNCOMPLETED
        # Jika tidak ada perubahan status, calculated_output tetap menggunakan old_output
        
        # Update detail
        try:
            detail.refresh_from_db()
            detail.start_time = start_time
            detail.stop_time = stop_time
            detail.job_operation = job_operation
            detail.ct = ct
            detail.pb = pb
            detail.is_uncompleted = new_is_uncompleted
            detail.output = calculated_output
            detail.comment = comment if comment else None
            detail.conn_no = conn_number  # ✅ UPDATE CONNECTOR
            detail.save()
        except ThreadDetail.DoesNotExist:
            pass
        
        # ✅ UPDATE CONNECTOR TABLE DENGAN VALIDASI
        if requires_connector and conn_number:
            # Cek apakah conn_number berubah
            if old_conn_no != conn_number:
                existing_connector = Connector.objects.filter(
                    bjo=bjo,
                    joint_number=detail.joint_number
                ).first()
                
                if existing_connector:
                    # Update jika conn_number berbeda
                    if existing_connector.conn_number != conn_number:
                        existing_connector.conn_number = conn_number
                        existing_connector.save()
                else:
                    # Create baru jika belum ada
                    Connector.objects.create(
                        bjo=bjo,
                        joint_number=detail.joint_number,
                        conn_number=conn_number
                    )
        
        # ===== HANDLE NCR STATUS BASED ON COMMENT =====
        new_comment = comment or ''
        has_ncr_in_new = 'NCR' in new_comment.upper()
        has_ncr_in_old = 'NCR' in old_comment.upper()
        
        # Cek apakah ada NCR record existing
        existing_ncr = ThreadNcr.objects.filter(serial=detail).exists()
        
        if has_ncr_in_new and not has_ncr_in_old:
            # ===== COMMENT BARU MENGANDUNG NCR, TAPI DULU TIDAK =====
            if not existing_ncr:
                # Create NCR baru
                try:
                    ThreadNcr.objects.create(serial=detail)
                    
                    # Update protector status
                    is_box_protector = BoxProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
                    is_pin_protector = PinProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
                    
                    if is_box_protector:
                        BoxProtector.objects.filter(
                            serial_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=True)
                    elif is_pin_protector:
                        PinProtector.objects.filter(
                            serial_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=True)
                    else:
                        SerialNumber.objects.filter(
                            joint_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=True)
                    
                    messages.warning(
                        request, 
                        f"Threading detail berhasil diupdate. Output: {calculated_output}. "
                        f"NCR record telah dibuat untuk joint '{detail.joint_number}'. "
                        "Silakan hubungi engineer untuk melengkapi detail NCR."
                    )
                except Exception as ncr_error:
                    messages.warning(
                        request,
                        f"Threading detail berhasil diupdate dengan output: {calculated_output}, "
                        f"namun gagal membuat NCR record: {str(ncr_error)}"
                    )
            else:
                messages.success(request, f"Threading detail berhasil diupdate. Output: {calculated_output}. NCR record sudah ada sebelumnya.")
                
        elif not has_ncr_in_new and has_ncr_in_old:
            # ===== COMMENT BARU TIDAK MENGANDUNG NCR, TAPI DULU ADA =====
            if existing_ncr:
                # Hapus NCR record
                try:
                    ThreadNcr.objects.filter(serial=detail).delete()
                    
                    # Update protector status - reset is_ncr
                    is_box_protector = BoxProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
                    is_pin_protector = PinProtector.objects.filter(serial_number=detail.joint_number, bjo=detail.bjo).exists()
                    
                    if is_box_protector:
                        BoxProtector.objects.filter(
                            serial_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=False)
                    elif is_pin_protector:
                        PinProtector.objects.filter(
                            serial_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=False)
                    else:
                        SerialNumber.objects.filter(
                            joint_number=detail.joint_number, 
                            bjo=detail.bjo
                        ).update(is_ncr=False)
                    
                    messages.success(
                        request, 
                        f"Threading detail berhasil diupdate. Output: {calculated_output}. "
                        f"NCR record telah dihapus karena comment tidak lagi mengandung 'NCR'."
                    )
                except Exception as ncr_error:
                    messages.warning(
                        request,
                        f"Threading detail berhasil diupdate dengan output: {calculated_output}, "
                        f"namun gagal menghapus NCR record: {str(ncr_error)}"
                    )
            else:
                messages.success(request, f"Threading detail berhasil diupdate. Output: {calculated_output}.")
                
        else:
            # ===== TIDAK ADA PERUBAHAN STATUS NCR =====
            if old_is_uncompleted == new_is_uncompleted:
                messages.success(request, f"Threading detail berhasil diupdate. Output: {calculated_output}.")
        
        return redirect('thread_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('thread_detail', header_id=header.id)

@threading_management_access_required
def thread_detail_delete(request, header_id):
    """Delete threading detail dengan auto restore jobDetail dan auto revert posted status"""
    header = get_object_or_404(ThreadHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                "Access Denied: Only Admin and Supervisor can delete details on posted records."
            )
            return redirect('thread_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada penghapusan detail."
            )
    
    if request.method != 'POST':
        messages.error(request, "Method tidak diizinkan.")
        return redirect('thread_detail', header_id=header.id)
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    
    try:
        with transaction.atomic():
            detail = ThreadDetail.objects.get(id=detail_id, Reff=header)
            
            joint_number = detail.joint_number
            pin_or_box = detail.pin_or_box
            bjo = detail.bjo
            is_rework_detail = 'REWORKED' in (detail.comment or '')
            is_uncompleted = detail.is_uncompleted
            output_value = detail.output or 0
            
            # Deteksi jenis protector/joint
            is_box_protector = BoxProtector.objects.filter(serial_number=joint_number, bjo=bjo).exists()
            is_pin_protector = PinProtector.objects.filter(serial_number=joint_number, bjo=bjo).exists()
            is_pipe = not is_box_protector and not is_pin_protector
            
            # ===== HAPUS JOBORDER DETAIL (TANPA MENGUBAH BJO.QTY) =====
            deleted_finished_value = 0
            if not is_rework_detail:
                try:
                    from decimal import Decimal
                    
                    if is_pipe:
                        # ✅ PIPE: uncompleted=0.25, completed=0.5
                        finished_val = Decimal('0.25') if is_uncompleted else Decimal('0.5')
                        deleted_count = jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=f"{pin_or_box} threading for {joint_number}",
                            finished=finished_val
                        ).delete()[0]
                        
                        if deleted_count > 0:
                            deleted_finished_value = float(finished_val)
                        
                    else:
                        # ✅ PROTECTOR: uncompleted=0.5, completed=1.0
                        finished_val = Decimal('0.5') if is_uncompleted else Decimal('1.0')
                        deleted_count = jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=joint_number,
                            finished=finished_val
                        ).delete()[0]
                        
                        if deleted_count > 0:
                            deleted_finished_value = float(finished_val)
                    
                except Exception as job_detail_error:
                    print(f"Warning: Gagal menghapus jobDetail: {str(job_detail_error)}")
            
            # ===== HAPUS NCR RECORDS TERKAIT =====
            try:
                ncr_deleted = ThreadNcr.objects.filter(serial=detail).delete()[0]
                if ncr_deleted > 0:
                    print(f"Info: {ncr_deleted} NCR record(s) dihapus untuk detail {detail.id}")
            except Exception as ncr_error:
                print(f"Warning: Gagal menghapus NCR records: {str(ncr_error)}")
            
            # Hapus detail threading
            detail.delete()
            
            # ===== RESET STATUS PROTECTOR/SERIAL =====
            if is_box_protector:
                remaining_details = ThreadDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo,
                    pin_or_box='BOX'
                ).exists()
                
                if not remaining_details:
                    BoxProtector.objects.filter(
                        serial_number=joint_number, 
                        bjo=bjo
                    ).update(is_threaded=False, is_rwk=False, is_ncr=False)
                else:
                    # Cek apakah masih ada NCR di detail lain
                    has_other_ncr = ThreadDetail.objects.filter(
                        joint_number=joint_number,
                        bjo=bjo,
                        pin_or_box='BOX'
                    ).exclude(id=detail_id).exists() and ThreadNcr.objects.filter(
                        serial__joint_number=joint_number,
                        serial__bjo=bjo,
                        serial__pin_or_box='BOX'
                    ).exists()
                    
                    if is_rework_detail:
                        BoxProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=False)
                    
                    # Reset is_ncr jika tidak ada NCR lagi
                    if not has_other_ncr:
                        BoxProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_ncr=False)
                        
            elif is_pin_protector:
                remaining_details = ThreadDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo,
                    pin_or_box='PIN'
                ).exists()
                
                if not remaining_details:
                    PinProtector.objects.filter(
                        serial_number=joint_number, 
                        bjo=bjo
                    ).update(is_threaded=False, is_rwk=False, is_ncr=False)
                else:
                    # Cek apakah masih ada NCR di detail lain
                    has_other_ncr = ThreadDetail.objects.filter(
                        joint_number=joint_number,
                        bjo=bjo,
                        pin_or_box='PIN'
                    ).exclude(id=detail_id).exists() and ThreadNcr.objects.filter(
                        serial__joint_number=joint_number,
                        serial__bjo=bjo,
                        serial__pin_or_box='PIN'
                    ).exists()
                    
                    if is_rework_detail:
                        PinProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=False)
                    
                    # Reset is_ncr jika tidak ada NCR lagi
                    if not has_other_ncr:
                        PinProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_ncr=False)
                        
            else:  # PIPE joint
                remaining_details_same_side = ThreadDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo,
                    pin_or_box=pin_or_box
                ).exists()
                
                remaining_details_any_side = ThreadDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo
                ).exists()
                
                # Reset status threading untuk sisi yang dihapus
                if not remaining_details_same_side:
                    if pin_or_box == 'PIN':
                        SerialNumber.objects.filter(
                            joint_number=joint_number, 
                            bjo=bjo
                        ).update(is_pin_threaded=False)
                    elif pin_or_box == 'BOX':
                        SerialNumber.objects.filter(
                            joint_number=joint_number, 
                            bjo=bjo
                        ).update(is_box_threaded=False)
                
                # Reset is_rwk jika tidak ada detail lagi di sisi yang sama
                if is_rework_detail and not remaining_details_same_side:
                    SerialNumber.objects.filter(
                        joint_number=joint_number, 
                        bjo=bjo
                    ).update(is_rwk=False)
                
                # Cek apakah masih ada NCR di detail lain untuk joint ini
                has_other_ncr = ThreadNcr.objects.filter(
                    serial__joint_number=joint_number,
                    serial__bjo=bjo
                ).exists()
                
                # Reset semua jika tidak ada detail sama sekali
                if not remaining_details_any_side:
                    SerialNumber.objects.filter(
                        joint_number=joint_number, 
                        bjo=bjo
                    ).update(
                        is_pin_threaded=False,
                        is_box_threaded=False,
                        is_rwk=False,
                        is_ncr=False
                    )
                # Reset is_ncr saja jika tidak ada NCR lagi
                elif not has_other_ncr:
                    SerialNumber.objects.filter(
                        joint_number=joint_number, 
                        bjo=bjo
                    ).update(is_ncr=False)
            
            # Update status is_finish BJO
            try:
                from decimal import Decimal
                total_finished = jobDetail.objects.filter(job=bjo).aggregate(
                    total=Sum('finished')
                )['total'] or Decimal(0)
                
                bjo.refresh_from_db()
                remaining_qty = float(bjo.qty) - float(total_finished)
                
                if remaining_qty > 0:
                    bjo.is_finish = False
                    bjo.save(update_fields=['is_finish'])
                    
            except Exception as status_error:
                print(f"Warning: Gagal mengupdate status is_finish: {str(status_error)}")
            
            # Success messages
            if is_rework_detail:
                messages.success(
                    request, 
                    f"REWORK detail threading untuk {joint_number} ({pin_or_box}) berhasil dihapus. "
                    f"Output yang dihapus: {output_value}. Status rework telah di-reset."
                )
            elif is_uncompleted:
                if deleted_finished_value > 0:
                    messages.success(
                        request, 
                        f"UNCOMPLETED detail threading untuk {joint_number} ({pin_or_box}) berhasil dihapus. "
                        f"Output yang dihapus: {output_value}. JobDetail (finished: -{deleted_finished_value}) telah dihapus. "
                        f"BJO {bjo.bjo} qty tetap: {bjo.qty}. Remaining akan bertambah +{deleted_finished_value}."
                    )
                else:
                    messages.success(
                        request, 
                        f"UNCOMPLETED detail threading untuk {joint_number} ({pin_or_box}) berhasil dihapus. "
                        f"Output yang dihapus: {output_value}. BJO {bjo.bjo} qty tetap: {bjo.qty}."
                    )
            else:
                messages.success(
                    request, 
                    f"Detail threading untuk {joint_number} ({pin_or_box}) berhasil dihapus. "
                    f"Output yang dihapus: {output_value}. JobDetail (finished: -{deleted_finished_value}) telah dihapus. "
                    f"BJO {bjo.bjo} qty tetap: {bjo.qty}. Remaining akan bertambah +{deleted_finished_value}."
                )
                
            return redirect('thread_detail', header_id=header.id)
            
    except ThreadDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus: {str(e)}")
        return redirect('thread_detail', header_id=header.id)

@threading_management_access_required
def handle_edit_time_thread_detail(request, header_id):
    """Handle edit threading detail time only with duration-based calculation"""
    header = get_object_or_404(ThreadHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit time on posted records.'
            )
            return redirect('thread_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan waktu."
            )
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    
    try:
        detail = ThreadDetail.objects.get(id=detail_id, Reff=header)
    except ThreadDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('thread_detail', header_id=header.id)
    
    try:
        # Ambil start time dan duration dari form
        start_time_str = request.POST.get('start_time')
        duration_hours_str = request.POST.get('duration_hours')
        
        if not start_time_str or not duration_hours_str:
            messages.error(request, "Start Time dan Duration wajib diisi.")
            return redirect('thread_detail', header_id=header.id)
        
        # Parse start time
        try:
            start_time = dt.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format start time tidak valid.")
            return redirect('thread_detail', header_id=header.id)
        
        # Parse duration
        try:
            duration_hours = float(duration_hours_str)
            if duration_hours <= 0:
                messages.error(request, "Duration harus lebih dari 0.")
                return redirect('thread_detail', header_id=header.id)
            if duration_hours > 16:
                messages.error(request, "Duration maksimal 16 jam.")
                return redirect('thread_detail', header_id=header.id)
        except ValueError:
            messages.error(request, "Format duration tidak valid.")
            return redirect('thread_detail', header_id=header.id)
        start_datetime = dt.combine(dt.today(), start_time)
        stop_datetime = start_datetime + timedelta(hours=duration_hours)
        stop_time = stop_datetime.time()
        if start_time == stop_time:
            messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
            return redirect('thread_detail', header_id=header.id)
        
        # Update detail
        detail.start_time = start_time
        detail.stop_time = stop_time
        detail.save()
        
        # Success message
        duration_display = f"{duration_hours:.1f}"
        
        messages.success(
            request, 
            f"Time berhasil diupdate. "
            f"Start: {start_time.strftime('%H:%M')}, "
            f"Duration: {duration_display} hours, "
            f"Stop: {stop_time.strftime('%H:%M')}"
        )
        
        return redirect('thread_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('thread_detail', header_id=header.id)

def thread_pdf(request):
    """Generate PDF untuk ThreadHeader dengan filter yang sama seperti thread_list - FIXED VERSION"""
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    headers = ThreadHeader.objects.select_related(
        'machine', 
        'shift', 
        'operator', 
        'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    headers = headers.order_by('-date', '-id')

    # PERBAIKAN: Hitung actual_hours DAN actual_output yang benar
    for header in headers:
        if not header.is_posted:
            detail_qs = ThreadDetail.objects.filter(Reff=header)
            total_hours = 0
            
            for detail in detail_qs:
                if detail.start_time and detail.stop_time:
                    duration_hours = calculate_time_duration(detail.start_time, detail.stop_time)
                    if duration_hours:
                        total_hours += duration_hours
            
            header.calculated_actual_hours = round(total_hours, 2)
            
            # FIXED: Gunakan SUM dari output, bukan COUNT
            total_output = detail_qs.aggregate(Sum('output'))['output__sum'] or 0
            header.calculated_actual_output = round(total_output, 2)
        else:
            header.calculated_actual_hours = float(header.actual_hours) if header.actual_hours else 0
            header.calculated_actual_output = float(header.actual_output) if header.actual_output else 0

    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))
    today = date.today()

    template_path = 'thread/pdf.html'
    context = {
        'headers': headers,
        'logo_url': logo_url,
        'today': today,
        'query': query,
        'filter_machine': filter_machine,
        'filter_date': filter_date,
        'filter_status': filter_status,
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="thread_record_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@threading_management_access_required
def finalisasi_thread(request, pk):
    header = get_object_or_404(ThreadHeader, pk=pk)

    # ===== CRITICAL: CT/PB VALIDATION =====
    def validate_ct_pb():
        details_without_ct = []
        details_without_pb = []

        for detail in ThreadDetail.objects.filter(Reff=header):
            if detail.ct is None or detail.ct == 0:
                details_without_ct.append({
                    'id': detail.id,
                    'bjo': detail.bjo.bjo,
                    'joint': detail.joint_number,
                    'job_op': detail.job_operation,
                    'pin_box': detail.pin_or_box,
                    'start_time': detail.start_time.strftime('%H:%M') if detail.start_time else '-',
                    'stop_time': detail.stop_time.strftime('%H:%M') if detail.stop_time else '-',
                })
            if detail.pb is None or detail.pb == 0:
                details_without_pb.append({
                    'id': detail.id,
                    'bjo': detail.bjo.bjo,
                    'joint': detail.joint_number,
                    'job_op': detail.job_operation,
                    'pin_box': detail.pin_or_box,
                    'start_time': detail.start_time.strftime('%H:%M') if detail.start_time else '-',
                    'stop_time': detail.stop_time.strftime('%H:%M') if detail.stop_time else '-',
                })

        return details_without_ct, details_without_pb

    # ===== RUN VALIDATION IMMEDIATELY =====
    missing_ct, missing_pb = validate_ct_pb()

    if missing_ct or missing_pb:
        error_message = "⚠️ Cannot finish record. Missing CT/PB values:\n\n"

        if missing_ct:
            error_message += f"❌ {len(missing_ct)} detail(s) without CT values:\n"
            for idx, detail in enumerate(missing_ct[:5], 1):
                error_message += (
                    f"  {idx}. BJO {detail['bjo']}, Joint {detail['joint']}, "
                    f"{detail['pin_box']}, Job Op {detail['job_op']}\n"
                    f"     Time: {detail['start_time']} - {detail['stop_time']}\n"
                )
            if len(missing_ct) > 5:
                error_message += f"  ... and {len(missing_ct) - 5} more\n"

        if missing_pb:
            error_message += f"\n❌ {len(missing_pb)} detail(s) without PB values:\n"
            for idx, detail in enumerate(missing_pb[:5], 1):
                error_message += (
                    f"  {idx}. BJO {detail['bjo']}, Joint {detail['joint']}, "
                    f"{detail['pin_box']}, Job Op {detail['job_op']}\n"
                    f"     Time: {detail['start_time']} - {detail['stop_time']}\n"
                )
            if len(missing_pb) > 5:
                error_message += f"  ... and {len(missing_pb) - 5} more\n"

        error_message += "\n💡 Please fill in CT and PB values for ALL details before finishing."
        error_message += "\n   Use the Edit (yellow) button in the detail list to update values."

        messages.error(request, error_message)
        return redirect('thread_detail', header_id=header.id)

    def calculate_totals():
        detail_qs = ThreadDetail.objects.filter(Reff=header)

        total_hours = 0
        for d in detail_qs:
            if d.start_time and d.stop_time:
                duration_hours = calculate_time_duration(d.start_time, d.stop_time)
                if duration_hours:
                    total_hours += duration_hours

        total_qty = detail_qs.aggregate(Sum('output'))['output__sum'] or 0
        total_qty = round(total_qty, 2)
        actual_output = total_qty
        actual_hours = round(total_hours, 2)

        return total_qty, total_hours, actual_output, actual_hours

    # ===== PREPARE BJO DATA =====
    bjos_in_shift = ThreadDetail.objects.filter(Reff=header).values_list('bjo', flat=True).distinct()
    bjos_list = JobHeader.objects.filter(id__in=bjos_in_shift)

    bjos_data = []
    for bjo in bjos_list:
        joint_numbers = ThreadDetail.objects.filter(
            Reff=header,
            bjo=bjo,
            is_uncompleted=False
        ).values_list('joint_number', flat=True).distinct()

        reason_stop = TreadReasonStop.objects.filter(
            Reff=header,
            bjo=bjo
        ).first()

        # ✅ Load existing maintenance per BJO
        existing_bjo_maintenance = Maintenance.objects.filter(
            machine=header,
            bjo=bjo
        ).first()

        bjos_data.append({
            'id': bjo.id,
            'bjo': bjo.bjo,
            'customer': bjo.customer,
            'size': bjo.size,
            'qty': bjo.qty,
            'joint_numbers': list(joint_numbers),
            'reject': reason_stop.reject if reason_stop else 0,
            'cutback': reason_stop.cutback if reason_stop else 0,
            'change_over': reason_stop.change_over if reason_stop else 0,
            'change_over_comment': reason_stop.change_over_comment if reason_stop else '',
            # ✅ BARU: maintenance per BJO
            'maint_duration': existing_bjo_maintenance.duration if existing_bjo_maintenance else 0,
            'maint_cost': existing_bjo_maintenance.cost if existing_bjo_maintenance else 0,
            'maint_issue': existing_bjo_maintenance.issue if existing_bjo_maintenance else '',
        })

    existing_shared_reason_stop = TreadReasonStop.objects.filter(Reff=header, bjo=None).first()

    # Initial calculation
    total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

    booked_duration = float(header.booked_hours.duration) if header.booked_hours else 0
    time_difference = 0
    need_reason_explanation = False
    is_overtime = False

    if request.method == "POST":
        # ===== RE-VALIDATE CT/PB ON POST =====
        missing_ct, missing_pb = validate_ct_pb()

        if missing_ct or missing_pb:
            error_message = "⚠️ Cannot finish record. Missing CT/PB values:\n\n"

            if missing_ct:
                error_message += f"❌ {len(missing_ct)} detail(s) without CT values:\n"
                for idx, detail in enumerate(missing_ct[:5], 1):
                    error_message += (
                        f"  {idx}. BJO {detail['bjo']}, Joint {detail['joint']}, "
                        f"{detail['pin_box']}, Job Op {detail['job_op']}\n"
                    )
                if len(missing_ct) > 5:
                    error_message += f"  ... and {len(missing_ct) - 5} more\n"

            if missing_pb:
                error_message += f"\n❌ {len(missing_pb)} detail(s) without PB values:\n"
                for idx, detail in enumerate(missing_pb[:5], 1):
                    error_message += (
                        f"  {idx}. BJO {detail['bjo']}, Joint {detail['joint']}, "
                        f"{detail['pin_box']}, Job Op {detail['job_op']}\n"
                    )
                if len(missing_pb) > 5:
                    error_message += f"  ... and {len(missing_pb) - 5} more\n"

            error_message += "\n💡 Please return to detail page and fill in CT/PB values for ALL details."

            messages.error(request, error_message)
            return redirect('thread_detail', header_id=header.id)

        # RECALCULATE totals
        total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

        actual_output = request.POST.get("actual_output")
        actual_hours = request.POST.get("actual_hours")
        comment = request.POST.get("comment", "").strip()

        if not actual_output:
            actual_output = str(auto_actual_output)
        if not actual_hours:
            actual_hours = str(auto_actual_hours)

        user_input_hours = float(actual_hours)

        if abs(user_input_hours - auto_actual_hours) <= 0.01:
            actual_hours = str(auto_actual_hours)
            actual_hours_float = auto_actual_hours
        elif request.POST.get('force_refresh') == 'true':
            actual_hours = str(auto_actual_hours)
            actual_hours_float = auto_actual_hours
        else:
            actual_hours_float = user_input_hours

        if total_qty == 0:
            messages.error(request, "Cannot complete finalization because details are still empty.")
            return redirect("thread_detail", pk=header.pk)

        if not actual_output or not actual_hours:
            messages.error(request, "Actual Output and Actual Hours are required.")
            return render(request, "thread/final.html", {
                "header": header,
                "total_qty": total_qty,
                "total_hours": round(total_hours, 2),
                "booked_duration": booked_duration,
                "time_difference": 0,
                "need_reason_explanation": False,
                "is_overtime": False,
                "bjos_data": bjos_data,
                "existing_shared_reason_stop": existing_shared_reason_stop,
                "auto_actual_output": auto_actual_output,
                "auto_actual_hours": auto_actual_hours,
            })

        time_difference = booked_duration - actual_hours_float

        if time_difference < -0.0167:
            is_overtime = True
            time_difference = abs(time_difference)
            need_reason_explanation = True
        elif time_difference > 0.0167:
            is_overtime = False
            need_reason_explanation = True
        else:
            is_overtime = False
            need_reason_explanation = False

        if need_reason_explanation:
            # ===== SHARED REASON STOPS (tanpa maintenance) =====
            waiting_materials_shared = request.POST.get("waiting_materials_shared", 0)
            meeting_shared = request.POST.get("meeting_shared", 0)
            others_shared = request.POST.get("others_shared", 0)

            total_shared_time = (
                float(waiting_materials_shared or 0) +
                float(meeting_shared or 0) +
                float(others_shared or 0)
            )

            # ===== PER BJO REASON STOPS =====
            total_per_bjo_time = 0
            bjo_reason_data = {}

            for bjo_item in bjos_data:
                bjo_id = bjo_item['id']
                reject = request.POST.get(f"reject_{bjo_id}", 0)
                cutback = request.POST.get(f"cutback_{bjo_id}", 0)
                change_over = request.POST.get(f"change_over_{bjo_id}", 0)
                change_over_comment = request.POST.get(f"change_over_comment_{bjo_id}", "").strip()
                rejected_joints_str = request.POST.get(f"rejected_joints_{bjo_id}", "").strip()
                rejected_joints = [j.strip() for j in rejected_joints_str.split(",") if j.strip()]

                # ✅ BARU: Per-BJO maintenance
                maint_duration = float(request.POST.get(f"maint_duration_{bjo_id}", 0) or 0)
                maint_cost = float(request.POST.get(f"maint_cost_{bjo_id}", 0) or 0)
                maint_issue = request.POST.get(f"maint_issue_{bjo_id}", "").strip()

                # ✅ change_over + maint_duration keduanya masuk total per BJO
                total_per_bjo_time += float(change_over or 0) + maint_duration

                bjo_reason_data[bjo_id] = {
                    'reject': int(reject or 0),
                    'cutback': int(cutback or 0),
                    'change_over': float(change_over or 0),
                    'change_over_comment': change_over_comment,
                    'rejected_joints': rejected_joints,
                    'maint_duration': maint_duration,
                    'maint_cost': maint_cost,
                    'maint_issue': maint_issue,
                }

            total_reason_time = total_shared_time + total_per_bjo_time

            # Validation: total must match time_difference
            reason_type = "overtime" if is_overtime else "remaining time"
            if abs(total_reason_time - time_difference) > 0.0167:
                messages.error(
                    request,
                    f"Total reason stop time ({total_reason_time:.2f} hours) MUST MATCH "
                    f"{reason_type} ({time_difference:.2f} hours). "
                    f"Cannot be more or less! "
                    f"(Shared: {total_shared_time:.2f} hrs + Per BJO: {total_per_bjo_time:.2f} hrs)"
                )
                return render(request, "thread/final.html", {
                    "header": header,
                    "total_qty": total_qty,
                    "total_hours": round(total_hours, 2),
                    "booked_duration": booked_duration,
                    "time_difference": round(time_difference, 2),
                    "need_reason_explanation": need_reason_explanation,
                    "is_overtime": is_overtime,
                    "bjos_data": bjos_data,
                    "existing_shared_reason_stop": existing_shared_reason_stop,
                    "actual_output": actual_output,
                    "actual_hours": actual_hours,
                    "auto_actual_output": auto_actual_output,
                    "auto_actual_hours": auto_actual_hours,
                })

            # ===== SAVE SHARED REASON STOP =====
            shared_reason_data = {
                'waiting_materials': float(waiting_materials_shared or 0),
                'meeting': float(meeting_shared or 0),
                'others': float(others_shared or 0),
                'maintenance': None,
                'reject': 0,
                'cutback': 0,
                'change_over': 0,
                'change_over_comment': '',
                'bjo_number': None,
                'joint_number': None,
            }

            TreadReasonStop.objects.filter(Reff=header, bjo=None).delete()
            TreadReasonStop.objects.create(Reff=header, bjo=None, **shared_reason_data)

            # ===== SAVE PER BJO REASON STOPS + MAINTENANCE =====
            for bjo_item in bjos_data:
                bjo_id = bjo_item['id']
                bjo_obj = JobHeader.objects.get(id=bjo_id)
                reason_data = bjo_reason_data.get(bjo_id, {})

                rejected_joints = reason_data.get('rejected_joints', [])
                reject_count = reason_data.get('reject', 0)
                cutback = reason_data.get('cutback', 0)
                change_over = reason_data.get('change_over', 0)
                change_over_comment = reason_data.get('change_over_comment', '')
                maint_duration = reason_data.get('maint_duration', 0)
                maint_cost = reason_data.get('maint_cost', 0)
                maint_issue = reason_data.get('maint_issue', '')

                # ✅ Handle Maintenance object per BJO
                maintenance_obj = None
                if maint_duration > 0:
                    maint_issue_final = maint_issue or f"Maintenance - BJO {bjo_obj.bjo} - {header.machine.name}"
                    try:
                        existing_maint = Maintenance.objects.filter(
                            machine=header,
                            bjo=bjo_obj
                        ).first()

                        if existing_maint:
                            existing_maint.duration = maint_duration
                            existing_maint.cost = maint_cost
                            existing_maint.issue = maint_issue_final
                            existing_maint.save()
                            maintenance_obj = existing_maint
                        else:
                            maintenance_obj = Maintenance.objects.create(
                                machine=header,
                                bjo=bjo_obj,
                                issue=maint_issue_final,
                                duration=maint_duration,
                                cost=maint_cost,
                            )
                    except Exception as e:
                        messages.error(request, f"Error saving maintenance for BJO {bjo_obj.bjo}: {e}")
                else:
                    # Hapus maintenance lama jika duration dikosongkan/0
                    Maintenance.objects.filter(machine=header, bjo=bjo_obj).delete()

                # Cleanup + create TreadReasonStop per BJO
                TreadReasonStop.objects.filter(Reff=header, bjo=bjo_obj).delete()

                if reject_count > 0 or cutback > 0 or change_over > 0 or maint_duration > 0:
                    rejected_joints_str = ','.join(rejected_joints) if rejected_joints else ''
                    TreadReasonStop.objects.create(
                        Reff=header,
                        bjo=bjo_obj,
                        bjo_number=bjo_obj.bjo,
                        joint_number=None,
                        reject=reject_count,
                        rejected_joints=rejected_joints_str,
                        cutback=cutback,
                        change_over=change_over,
                        change_over_comment=change_over_comment,
                        maintenance=maintenance_obj,  # ✅ FK ke Maintenance per BJO
                        waiting_materials=None,
                        meeting=None,
                        others=None,
                    )

        # ===== SAVE FINALIZATION =====
        header.actual_output = actual_output
        header.actual_hours = actual_hours
        header.comment = comment
        header.is_posted = True
        header.save()

        messages.success(
            request,
            f"✅ Threading record finalization successfully saved. "
            f"Total details: {ThreadDetail.objects.filter(Reff=header).count()}. "
            f"All CT and PB values validated."
        )
        return redirect("thread_list")

    # ===== GET REQUEST =====
    total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

    return render(request, "thread/final.html", {
        "header": header,
        "total_qty": total_qty,
        "total_hours": round(total_hours, 2),
        "booked_duration": booked_duration,
        "time_difference": 0,
        "need_reason_explanation": False,
        "is_overtime": False,
        "bjos_data": bjos_data,
        "existing_shared_reason_stop": existing_shared_reason_stop,
        "auto_actual_output": auto_actual_output,
        "auto_actual_hours": auto_actual_hours,
    })
    
def process_list(request):
    # Ambil semua data process, urutkan terbaru
    process_qs = Process.objects.all().order_by('-created_at')

    # Pagination (10 data per halaman)
    paginator = Paginator(process_qs, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    return render(request, 'process/list.html', {
    'items': items,
    'active_menu': 'process'
})

    
def process_add(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        rate = request.POST.get('rate')

        if not name:
            messages.error(request, "Nama Process wajib diisi.")
            return redirect('process_add')

        if not rate:
            messages.error(request, "Rate wajib diisi.")
            return redirect('process_add')

        try:
            rate_value = float(rate)
        except ValueError:
            messages.error(request, "Rate harus berupa angka.")
            return redirect('process_add')

        Process.objects.create(name=name, rate=rate_value)
        messages.success(request, "Process berhasil ditambahkan.")
        return redirect('process_list')

    return render(request, 'process/add.html', {
    'active_menu': 'process'
})

def process_edit(request, pk):
    item = get_object_or_404(Process, pk=pk)
    old_rate = item.rate

    if request.method == 'POST':
        item.name = request.POST.get('name', "").strip()
        rate = request.POST.get('rate', "").strip()

        # Validasi input kosong
        if not item.name or rate == "":
            messages.error(request, "Nama dan Rate wajib diisi.")
            return redirect('process_edit', pk=pk)

        # Konversi ke Decimal dengan aman
        try:
            new_rate = Decimal(rate)
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Rate harus berupa angka desimal.")
            return redirect('process_edit', pk=pk)

        # Update semua cycle time dan price book jika rate berubah
        if old_rate != new_rate:
            # Update Cycle Time
            cycle_times = CycleTime.objects.filter(process_type=item)
            ct_updated_count = 0
            for ct in cycle_times:
                if ct.hours is not None:  # pastikan tidak None
                    ct.cost = new_rate * ct.hours
                    ct.save()
                    ct_updated_count += 1

            # Update Price Book
            price_books = PriceBook.objects.filter(
                process_type=item,
                time_in_h__isnull=False
            )
            pb_updated_count = 0
            for pb in price_books:
                if pb.time_in_h not in (None, "", " "):  # cegah kosong
                    pb.cost_per_end = new_rate * pb.time_in_h
                    pb.cost_per_joint = pb.cost_per_end * 2
                    pb.cost_vtl = pb.cost_per_end
                    pb.save()
                    pb_updated_count += 1

            # Pesan sukses
            if ct_updated_count > 0 and pb_updated_count > 0:
                messages.success(
                    request,
                    f"Process berhasil diperbarui. {ct_updated_count} data Cycle Time dan {pb_updated_count} data Price Book telah diupdate otomatis."
                )
            elif ct_updated_count > 0:
                messages.success(
                    request,
                    f"Process berhasil diperbarui. {ct_updated_count} data Cycle Time telah diupdate otomatis."
                )
            elif pb_updated_count > 0:
                messages.success(
                    request,
                    f"Process berhasil diperbarui. {pb_updated_count} data Price Book telah diupdate otomatis."
                )
            else:
                messages.success(request, "Process berhasil diperbarui.")
        else:
            messages.success(request, "Process berhasil diperbarui.")

        # Simpan perubahan rate ke Process
        item.rate = new_rate
        item.save()

        return redirect('process_list')

    return render(request, 'process/edit.html', {
        'item': item,
        'active_menu': 'process'
    })
    
def process_delete(request, id):
    """
    View untuk menghapus Process
    Karena Process terkait dengan CycleTime dan PriceBook, perlu penanganan khusus
    """
    if request.method == 'POST':
        try:
            process = get_object_or_404(Process, id=id)
            name = process.name
            
            # Cek data terkait sebelum menghapus
            cycle_times_count = CycleTime.objects.filter(process_type=process).count()
            price_books_count = PriceBook.objects.filter(process_type=process).count()
            
            # Hapus data terkait terlebih dahulu (cascade delete)
            if cycle_times_count > 0:
                CycleTime.objects.filter(process_type=process).delete()
            
            if price_books_count > 0:
                PriceBook.objects.filter(process_type=process).delete()
            
            # Hapus process
            process.delete()
            
            # Buat pesan sukses yang informatif
            success_msg = f'Process "{name}" berhasil dihapus.'
            if cycle_times_count > 0 and price_books_count > 0:
                success_msg += f' ({cycle_times_count} data Cycle Time dan {price_books_count} data Price Book juga ikut terhapus)'
            elif cycle_times_count > 0:
                success_msg += f' ({cycle_times_count} data Cycle Time juga ikut terhapus)'
            elif price_books_count > 0:
                success_msg += f' ({price_books_count} data Price Book juga ikut terhapus)'
            
            messages.success(request, success_msg)
            
            # Redirect kembali ke list dengan pagination yang sama
            redirect_url = reverse('process_list')
            query_params = []
            
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Process: {str(e)}')
            return redirect('process_list')
    
    return redirect('process_list')

def materialgrade_list(request):
    query = request.GET.get('q', '')
    grade_qs = MaterialGrade.objects.all().order_by('-created_at')

    if query:
        grade_qs = grade_qs.filter(
            Q(name__icontains=query)
        )

    paginator = Paginator(grade_qs, 10)
    page = request.GET.get('page')
    items = paginator.get_page(page)

    return render(request, 'materialgrade/list.html', {
        'items': items,
        'query': query,
        'active_menu': 'material_grade',
    })

def materialgrade_add(request):
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            
            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Material Grade tidak boleh kosong.')
                return render(request, 'materialgrade/add.html', {'active_menu': 'material_grade'})
            
            # Cek apakah nama sudah ada
            if MaterialGrade.objects.filter(name=name).exists():
                messages.error(request, f'Material Grade dengan nama "{name}" sudah ada.')
                return render(request, 'materialgrade/add.html', {
                    'active_menu': 'material_grade',
                    'name': name
                })
            
            MaterialGrade.objects.create(name=name)
            messages.success(request, f'Material Grade "{name}" berhasil ditambahkan.')
            return redirect('materialgrade_list')
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Material Grade: {str(e)}')
            return render(request, 'materialgrade/add.html', {'active_menu': 'material_grade'})
    
    return render(request, 'materialgrade/add.html', {'active_menu': 'material_grade'})

def materialgrade_edit(request, pk):
    item = get_object_or_404(MaterialGrade, pk=pk)
    
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            
            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Material Grade tidak boleh kosong.')
                return render(request, 'materialgrade/edit.html', {
                    'item': item, 
                    'active_menu': 'material_grade'
                })
            
            # Cek apakah nama sudah ada (kecuali untuk item yang sedang diedit)
            if MaterialGrade.objects.filter(name=name).exclude(pk=pk).exists():
                messages.error(request, f'Material Grade dengan nama "{name}" sudah ada.')
                return render(request, 'materialgrade/edit.html', {
                    'item': item, 
                    'active_menu': 'material_grade'
                })
            
            # Update data
            old_name = item.name
            item.name = name
            item.save()
            
            messages.success(request, f'Material Grade "{old_name}" berhasil diperbarui menjadi "{name}".')
            return redirect('materialgrade_list')
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Material Grade: {str(e)}')
            return render(request, 'materialgrade/edit.html', {
                'item': item, 
                'active_menu': 'material_grade'
            })
    
    return render(request, 'materialgrade/edit.html', {
        'item': item, 
        'active_menu': 'material_grade'
    })

def materialgrade_delete(request, id):
    """
    View untuk menghapus Material Grade
    """
    if request.method == 'POST':
        try:
            grade = get_object_or_404(MaterialGrade, id=id)
            name = grade.name
            grade.delete()
            
            messages.success(request, f'Material Grade "{name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('materialgrade_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Material Grade: {str(e)}')
            return redirect('materialgrade_list')
    
    return redirect('materialgrade_list')
    
def machine_list(request):
    query = request.GET.get('q', '')
    items = Machine.objects.all().order_by('-created_at')

    if query:
        items = items.filter(
            Q(name__icontains=query) |
            Q(process_type__name__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'active_menu': 'machine'
    }
    return render(request, 'machine/list.html', context)

def machine_add(request):
    processes = Process.objects.all().order_by('name')

    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            process_type_id = request.POST.get('process_type')
            capacity = request.POST.get('machine_capacity')

            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Mesin tidak boleh kosong.')
                return render(request, 'machine/add.html', {
                    'processes': processes,
                    'active_menu': 'machine'
                })

            # Cek apakah nama sudah ada
            if Machine.objects.filter(name=name).exists():
                messages.error(request, f'Mesin dengan nama "{name}" sudah ada.')
                return render(request, 'machine/add.html', {
                    'processes': processes,
                    'active_menu': 'machine',
                    'name': name,
                    'process_type_id': process_type_id,
                    'machine_capacity': capacity
                })

            process_type = Process.objects.get(id=process_type_id) if process_type_id else None
            Machine.objects.create(
                name=name,
                process_type=process_type,
                machine_capacity=capacity if capacity else None
            )

            messages.success(request, f'Mesin "{name}" berhasil ditambahkan.')
            return redirect('machine_list')

        except Process.DoesNotExist:
            messages.error(request, 'Process Type yang dipilih tidak valid.')
            return render(request, 'machine/add.html', {
                'processes': processes,
                'active_menu': 'machine'
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Mesin: {str(e)}')
            return render(request, 'machine/add.html', {
                'processes': processes,
                'active_menu': 'machine'
            })
    
    return render(request, 'machine/add.html', {
        'processes': processes,
        'active_menu': 'machine'
    })

def machine_edit(request, pk):
    item = get_object_or_404(Machine, pk=pk)
    processes = Process.objects.all().order_by('name')

    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            process_type_id = request.POST.get('process_type')
            capacity = request.POST.get('machine_capacity')

            # Validasi nama tidak boleh kosong
            if not name:
                messages.error(request, 'Nama Mesin tidak boleh kosong.')
                return render(request, 'machine/edit.html', {
                    'item': item,
                    'processes': processes,
                    'active_menu': 'machine'
                })

            # Cek apakah nama sudah ada (kecuali untuk item yang sedang diedit)
            if Machine.objects.filter(name=name).exclude(pk=pk).exists():
                messages.error(request, f'Mesin dengan nama "{name}" sudah ada.')
                return render(request, 'machine/edit.html', {
                    'item': item,
                    'processes': processes,
                    'active_menu': 'machine'
                })

            # Update data
            old_name = item.name
            item.name = name
            item.process_type = Process.objects.get(id=process_type_id) if process_type_id else None
            item.machine_capacity = capacity if capacity else None
            item.save()

            messages.success(request, f'Mesin "{old_name}" berhasil diperbarui menjadi "{name}".')
            return redirect('machine_list')

        except Process.DoesNotExist:
            messages.error(request, 'Process Type yang dipilih tidak valid.')
            return render(request, 'machine/edit.html', {
                'item': item,
                'processes': processes,
                'active_menu': 'machine'
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Mesin: {str(e)}')
            return render(request, 'machine/edit.html', {
                'item': item,
                'processes': processes,
                'active_menu': 'machine'
            })

    return render(request, 'machine/edit.html', {
        'item': item,
        'processes': processes,
        'active_menu': 'machine'
    })

def machine_delete(request, id):
    """
    View untuk menghapus Machine
    """
    if request.method == 'POST':
        try:
            machine = get_object_or_404(Machine, id=id)
            name = machine.name
            machine.delete()
            
            messages.success(request, f'Mesin "{name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('machine_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Mesin: {str(e)}')
            return redirect('machine_list')
    
    return redirect('machine_list')

@maintenance_access_required
def maintenance_list(request):
    query = request.GET.get('q', '')
    machine_id = request.GET.get('machine', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Query unified maintenance table with proper select_related
    items = Maintenance.objects.select_related(
        'machine__machine',  # For ThreadHeader -> Machine
        'weld_machine__machine',  # For WeldHeader -> Machine  
        'bevel_machine__machine',  # For BevelHeader -> Machine
        'machine__operator',  # For ThreadHeader -> Operator
        'weld_machine__operator',  # For WeldHeader -> Operator
        'bevel_machine__operator'  # For BevelHeader -> Operator
    ).all().order_by('-id')

    # Search filter
    if query:
        items = items.filter(
            Q(machine__machine__name__icontains=query) |  # ThreadHeader machine name
            Q(weld_machine__machine__name__icontains=query) |  # WeldHeader machine name
            Q(bevel_machine__machine__name__icontains=query) |  # BevelHeader machine name
            Q(issue__icontains=query) |
            Q(machine__operator__name__icontains=query) |  # ThreadHeader operator name
            Q(weld_machine__operator__name__icontains=query) |  # WeldHeader operator name
            Q(bevel_machine__operator__name__icontains=query)  # BevelHeader operator name
        )

    # Machine filter
    if machine_id:
        items = items.filter(
            Q(machine__machine_id=machine_id) |  # ThreadHeader machine
            Q(weld_machine__machine_id=machine_id) |  # WeldHeader machine
            Q(bevel_machine__machine_id=machine_id)  # BevelHeader machine
        )

    # Date range filter
    if start_date:
        items = items.filter(
            Q(machine__date__gte=start_date) |  # ThreadHeader date
            Q(weld_machine__date__gte=start_date) |  # WeldHeader date
            Q(bevel_machine__date__gte=start_date)  # BevelHeader date
        )
    
    if end_date:
        items = items.filter(
            Q(machine__date__lte=end_date) |  # ThreadHeader date
            Q(weld_machine__date__lte=end_date) |  # WeldHeader date
            Q(bevel_machine__date__lte=end_date)  # BevelHeader date
        )

    # Get all machines for filter dropdown
    machines = Machine.objects.all().order_by('name')

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'machines': machines,
        'selected_machine': machine_id,
        'start_date': start_date,
        'end_date': end_date,
        'active_menu': 'maintenance'
    }
    return render(request, 'maintenance/list.html', context)


@maintenance_access_required
def maintenance_export_excel(request):
    query = request.GET.get('q', '')
    machine_id = request.GET.get('machine', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Query unified maintenance table with same filters as list view
    items = Maintenance.objects.select_related(
        'machine__machine',
        'weld_machine__machine',
        'bevel_machine__machine',
        'machine__operator',
        'weld_machine__operator',
        'bevel_machine__operator'
    ).all().order_by('-id')

    # Apply same filters
    if query:
        items = items.filter(
            Q(machine__machine__name__icontains=query) |
            Q(weld_machine__machine__name__icontains=query) |
            Q(bevel_machine__machine__name__icontains=query) |
            Q(issue__icontains=query) |
            Q(machine__operator__name__icontains=query) |
            Q(weld_machine__operator__name__icontains=query) |
            Q(bevel_machine__operator__name__icontains=query)
        )

    if machine_id:
        items = items.filter(
            Q(machine__machine_id=machine_id) |
            Q(weld_machine__machine_id=machine_id) |
            Q(bevel_machine__machine_id=machine_id)
        )

    if start_date:
        items = items.filter(
            Q(machine__date__gte=start_date) |
            Q(weld_machine__date__gte=start_date) |
            Q(bevel_machine__date__gte=start_date)
        )
    
    if end_date:
        items = items.filter(
            Q(machine__date__lte=end_date) |
            Q(weld_machine__date__lte=end_date) |
            Q(bevel_machine__date__lte=end_date)
        )

    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan Maintenance"

    # Define styles
    header_font = Font(bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    cell_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    center_alignment = Alignment(horizontal="center", vertical="center")
    
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Set column widths
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 25
    ws.column_dimensions['D'].width = 35
    ws.column_dimensions['E'].width = 12
    ws.column_dimensions['F'].width = 12
    ws.column_dimensions['G'].width = 15
    ws.column_dimensions['H'].width = 20

    # Add title
    ws.merge_cells('A1:H1')
    title_cell = ws['A1']
    title_cell.value = "LAPORAN MAINTENANCE"
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = center_alignment
    title_cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

    # Add filter info
    row = 2
    if start_date or end_date or machine_id or query:
        ws.merge_cells(f'A{row}:H{row}')
        filter_info = "Filter: "
        filter_parts = []
        
        if start_date and end_date:
            filter_parts.append(f"Periode: {start_date} s/d {end_date}")
        elif start_date:
            filter_parts.append(f"Dari: {start_date}")
        elif end_date:
            filter_parts.append(f"Sampai: {end_date}")
        
        if machine_id:
            try:
                machine = Machine.objects.get(id=machine_id)
                filter_parts.append(f"Mesin: {machine.name}")
            except:
                pass
        
        if query:
            filter_parts.append(f"Pencarian: {query}")
        
        ws[f'A{row}'].value = filter_info + " | ".join(filter_parts)
        ws[f'A{row}'].font = Font(italic=True, size=10)
        ws[f'A{row}'].alignment = cell_alignment
        row += 1

    # Add export date
    ws.merge_cells(f'A{row}:H{row}')
    ws[f'A{row}'].value = f"Diekspor pada: {datetime.now().strftime('%d %B %Y %H:%M:%S')}"
    ws[f'A{row}'].font = Font(italic=True, size=9)
    ws[f'A{row}'].alignment = cell_alignment
    row += 1

    # Add empty row
    row += 1

    # Add headers
    headers = ['No', 'Tipe Proses', 'Mesin', 'Masalah', 'Durasi (jam)', 'Biaya', 'Tanggal', 'Operator']
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col_num)
        cell.value = header
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Add data
    for idx, item in enumerate(items, 1):
        row += 1
        
        # Get related header (either ThreadHeader, WeldHeader, or BevelHeader)
        related_header = item.machine if item.machine else (item.weld_machine if item.weld_machine else item.bevel_machine)
        
        # Get machine name
        machine_name = related_header.machine.name if related_header and related_header.machine else '-'
        
        # Get operator name from related header
        operator_name = '-'
        if related_header and hasattr(related_header, 'operator') and related_header.operator:
            operator_name = related_header.operator.name
        elif related_header and hasattr(related_header, 'operator_name') and related_header.operator_name:
            operator_name = related_header.operator_name
        
        # Get date
        date_value = related_header.date.strftime('%Y-%m-%d') if related_header and related_header.date else '-'
        
        # Data row
        data = [
            idx,
            item.process_type,
            machine_name,
            item.issue if item.issue else '-',
            item.duration if item.duration else '-',
            f"${item.cost:.2f}" if item.cost else '-',
            date_value,
            operator_name
        ]
        
        for col_num, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_num)
            cell.value = value
            cell.border = thin_border
            
            # Alignment
            if col_num == 1:  # No
                cell.alignment = center_alignment
            elif col_num == 2:  # Tipe Proses
                cell.alignment = center_alignment
            elif col_num in [5, 6]:  # Durasi, Biaya
                cell.alignment = center_alignment
            elif col_num == 7:  # Tanggal
                cell.alignment = center_alignment
            else:
                cell.alignment = cell_alignment

    # Add summary row
    row += 2
    ws.merge_cells(f'A{row}:D{row}')
    summary_cell = ws[f'A{row}']
    summary_cell.value = f"Total Data: {items.count()} maintenance"
    summary_cell.font = Font(bold=True, size=11)
    summary_cell.alignment = cell_alignment

    # Prepare response
    filename = f"Laporan_Maintenance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response

@maintenance_write_access_required
def maintenance_edit(request, pk):
    item = get_object_or_404(Maintenance, pk=pk)
    
    if request.method == 'POST':
        try:
            # Update field yang bisa diedit
            issue = request.POST.get('issue')
            duration = request.POST.get('duration')
            cost = request.POST.get('cost')
            
            # Validasi
            if not duration or not cost:
                messages.error(request, "Durasi dan Biaya wajib diisi.")
                return render(request, 'maintenance/edit.html', {
                    'item': item,
                    'active_menu': 'maintenance'
                })
            
            # Validasi numeric
            try:
                duration_float = float(duration)
                cost_float = float(cost)
                
                # Validasi range
                if duration_float < 0:
                    messages.error(request, "Durasi tidak boleh negatif.")
                    return render(request, 'maintenance/edit.html', {
                        'item': item,
                        'active_menu': 'maintenance'
                    })
                    
                if cost_float < 0:
                    messages.error(request, "Biaya tidak boleh negatif.")
                    return render(request, 'maintenance/edit.html', {
                        'item': item,
                        'active_menu': 'maintenance'
                    })
                    
            except ValueError:
                messages.error(request, "Durasi dan Biaya harus berupa angka valid.")
                return render(request, 'maintenance/edit.html', {
                    'item': item,
                    'active_menu': 'maintenance'
                })
            
            # Update data
            item.issue = issue
            item.duration = duration_float
            item.cost = cost_float
            item.save()
            
            machine_info = f"{item.related_header.machine.name} ({item.process_type})"
            messages.success(request, f"Data maintenance {machine_info} berhasil diperbarui.")
            return redirect('maintenance_list')
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Maintenance: {str(e)}')
            return render(request, 'maintenance/edit.html', {
                'item': item,
                'active_menu': 'maintenance'
            })
    
    return render(request, 'maintenance/edit.html', {
        'item': item,
        'active_menu': 'maintenance'
    })

@maintenance_delete_access_required
def maintenance_delete(request, id):
    """
    View untuk menghapus Maintenance
    """
    if request.method == 'POST':
        try:
            maintenance = get_object_or_404(Maintenance, id=id)
            
            # Get machine name dan process type untuk display
            header = maintenance.related_header
            machine_name = header.machine.name if header and header.machine else "Unknown Machine"
            process_type = maintenance.process_type
            maintenance_info = f"{machine_name} ({process_type}) - {header.date if header else 'No Date'}"
            
            # Cek apakah maintenance ini masih digunakan di reason stop
            thread_reason_exists = TreadReasonStop.objects.filter(maintenance=maintenance).exists()
            weld_reason_exists = WeldReasonStop.objects.filter(maintenance=maintenance).exists()
            
            if thread_reason_exists or weld_reason_exists:
                messages.error(request, f'Maintenance "{maintenance_info}" tidak bisa dihapus karena masih digunakan dalam reason stop.')
                return redirect('maintenance_list')
            
            maintenance.delete()
            messages.success(request, f'Maintenance "{maintenance_info}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('maintenance_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Maintenance: {str(e)}')
            return redirect('maintenance_list')
    
    return redirect('maintenance_list')

def odthickness_list(request):
    query = request.GET.get('q', '')

    items = OdThickness.objects.annotate(
        combined_name=Concat(
            'process_type__name',
            Value(' '),
            'size'
        )
    ).order_by('-created_at')

    if query:
        items = items.filter(
            Q(size__icontains=query) |
            Q(process_type__name__icontains=query) |
            Q(od__icontains=query) |
            Q(wall__icontains=query) |
            Q(combined_name__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'active_menu': 'od_thickness',
    }
    return render(request, 'odthickness/list.html', context)

def odthickness_add(request):
    processes = Process.objects.all().order_by('name')

    if request.method == 'POST':
        try:
            od = request.POST.get('od')
            wall = request.POST.get('wall')
            size = request.POST.get('size')
            process_type_id = request.POST.get('process_type')

            # Validasi wajib
            if not od or not wall or not size:
                messages.error(request, "OD, Wall, dan Size wajib diisi.")
                return render(request, 'odthickness/add.html', {
                    'processes': processes,
                    'active_menu': 'od_thickness',
                    'od': od,
                    'wall': wall,
                    'size': size,
                    'process_type_id': process_type_id
                })

            # Validasi numeric untuk OD dan Wall
            try:
                float(od)
                float(wall)
            except ValueError:
                messages.error(request, "OD dan Wall harus berupa angka.")
                return render(request, 'odthickness/add.html', {
                    'processes': processes,
                    'active_menu': 'od_thickness',
                    'od': od,
                    'wall': wall,
                    'size': size,
                    'process_type_id': process_type_id
                })

            # Cek duplikasi berdasarkan kombinasi od, wall, size, dan process_type
            process_type = Process.objects.get(id=process_type_id) if process_type_id else None
            
            existing = OdThickness.objects.filter(
                od=od,
                wall=wall,
                size=size,
                process_type=process_type
            ).exists()

            if existing:
                messages.error(request, "OD Thickness dengan kombinasi data ini sudah ada.")
                return render(request, 'odthickness/add.html', {
                    'processes': processes,
                    'active_menu': 'od_thickness',
                    'od': od,
                    'wall': wall,
                    'size': size,
                    'process_type_id': process_type_id
                })

            OdThickness.objects.create(
                od=od,
                wall=wall,
                size=size,
                process_type=process_type
            )

            messages.success(request, "OD Thickness berhasil ditambahkan.")
            return redirect('odthickness_list')

        except Process.DoesNotExist:
            messages.error(request, 'Process Type yang dipilih tidak valid.')
            return render(request, 'odthickness/add.html', {
                'processes': processes,
                'active_menu': 'od_thickness'
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah OD Thickness: {str(e)}')
            return render(request, 'odthickness/add.html', {
                'processes': processes,
                'active_menu': 'od_thickness'
            })

    return render(request, 'odthickness/add.html', {
        'processes': processes,
        'active_menu': 'od_thickness'
    })

def odthickness_edit(request, pk):
    item = get_object_or_404(OdThickness, pk=pk)
    processes = Process.objects.all().order_by('name')

    if request.method == 'POST':
        try:
            od = request.POST.get('od')
            wall = request.POST.get('wall')
            size = request.POST.get('size')
            process_type_id = request.POST.get('process_type')

            # Validasi wajib diisi
            if not od or not wall or not size:
                messages.error(request, "OD, Wall, dan Size wajib diisi.")
                return render(request, 'odthickness/edit.html', {
                    'item': item,   
                    'processes': processes,
                    'active_menu': 'od_thickness'
                })

            # Validasi numeric untuk OD dan Wall
            try:
                float(od)
                float(wall)
            except ValueError:
                messages.error(request, "OD dan Wall harus berupa angka.")
                return render(request, 'odthickness/edit.html', {
                    'item': item,   
                    'processes': processes,
                    'active_menu': 'od_thickness'
                })

            # Cek duplikasi (kecuali item yang sedang diedit)
            process_type = Process.objects.get(id=process_type_id) if process_type_id else None
            
            existing = OdThickness.objects.filter(
                od=od,
                wall=wall,
                size=size,
                process_type=process_type
            ).exclude(pk=pk).exists()

            if existing:
                messages.error(request, "OD Thickness dengan kombinasi data ini sudah ada.")
                return render(request, 'odthickness/edit.html', {
                    'item': item,   
                    'processes': processes,
                    'active_menu': 'od_thickness'
                })

            # Update data
            item.od = od
            item.wall = wall
            item.size = size
            item.process_type = process_type
            item.save()

            messages.success(request, "OD Thickness berhasil diperbarui.")
            return redirect('odthickness_list')

        except Process.DoesNotExist:
            messages.error(request, 'Process Type yang dipilih tidak valid.')
            return render(request, 'odthickness/edit.html', {
                'item': item,   
                'processes': processes,
                'active_menu': 'od_thickness'
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate OD Thickness: {str(e)}')
            return render(request, 'odthickness/edit.html', {
                'item': item,   
                'processes': processes,
                'active_menu': 'od_thickness'
            })

    return render(request, 'odthickness/edit.html', {
        'item': item,   
        'processes': processes,
        'active_menu': 'od_thickness'
    })

def odthickness_delete(request, id):
    """
    View untuk menghapus OD Thickness
    """
    if request.method == 'POST':
        try:
            odthickness = get_object_or_404(OdThickness, id=id)
            
            # Buat identifier untuk pesan
            identifier = f"{odthickness.process_type.name if odthickness.process_type else ''} {odthickness.size}".strip()
            if not identifier:
                identifier = f"OD: {odthickness.od}, Wall: {odthickness.wall}"
            
            odthickness.delete()
            
            messages.success(request, f'OD Thickness "{identifier}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('odthickness_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus OD Thickness: {str(e)}')
            return redirect('odthickness_list')
    
    return redirect('odthickness_list')

def infotag_list(request):
    query = request.GET.get('q', '')
    
    items = InfoTag.objects.all().order_by('-created_at')

    if query:
        items = items.filter(
            Q(name__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'active_menu': 'info_tag',
    }
    return render(request, 'infotag/list.html', context)

def infotag_add(request):
    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()

            # Validasi wajib
            if not name:
                messages.error(request, "Nama wajib diisi.")
                return render(request, 'infotag/add.html', {
                    'active_menu': 'info_tag',
                    'name': name
                })

            # Cek duplikasi nama (case insensitive)
            existing = InfoTag.objects.filter(name__iexact=name).exists()

            if existing:
                messages.error(request, "Info Tag dengan nama ini sudah ada.")
                return render(request, 'infotag/add.html', {
                    'active_menu': 'info_tag',
                    'name': name
                })

            InfoTag.objects.create(name=name)
            
            messages.success(request, "Info Tag berhasil ditambahkan.")
            return redirect('infotag_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Info Tag: {str(e)}')
            return render(request, 'infotag/add.html', {
                'active_menu': 'info_tag'
            })

    return render(request, 'infotag/add.html', {
        'active_menu': 'info_tag'
    })

def infotag_edit(request, pk):
    item = get_object_or_404(InfoTag, pk=pk)

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()

            # Validasi wajib diisi
            if not name:
                messages.error(request, "Nama wajib diisi.")
                return render(request, 'infotag/edit.html', {
                    'item': item,
                    'active_menu': 'info_tag'
                })

            # Cek duplikasi (kecuali item yang sedang diedit)
            existing = InfoTag.objects.filter(name__iexact=name).exclude(pk=pk).exists()

            if existing:
                messages.error(request, "Info Tag dengan nama ini sudah ada.")
                return render(request, 'infotag/edit.html', {
                    'item': item,
                    'active_menu': 'info_tag'
                })

            # Update data
            item.name = name
            item.save()

            messages.success(request, "Info Tag berhasil diperbarui.")
            return redirect('infotag_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Info Tag: {str(e)}')
            return render(request, 'infotag/edit.html', {
                'item': item,
                'active_menu': 'info_tag'
            })

    return render(request, 'infotag/edit.html', {
        'item': item,
        'active_menu': 'info_tag'
    })

def infotag_delete(request, id):
    """
    View untuk menghapus Info Tag
    """
    if request.method == 'POST':
        try:
            infotag = get_object_or_404(InfoTag, id=id)
            
            # Simpan nama untuk pesan
            tag_name = infotag.name
            
            infotag.delete()
            
            messages.success(request, f'Info Tag "{tag_name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('infotag_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Info Tag: {str(e)}')
            return redirect('infotag_list')
    
    return redirect('infotag_list')
    
def cycletime_list(request):
    query = request.GET.get('q', '')
    filter_process = request.GET.get('process', '')
    filter_status = request.GET.get('status', '')
    
    ct_qs = CycleTime.objects.select_related('process_type', 'od_thickness', 'ct_for').order_by('-created_at')

    # Filter pencarian
    if query:
        ct_qs = ct_qs.filter(
            Q(process_type__name__icontains=query) |
            Q(od_thickness__size__icontains=query) |
            Q(ct_for__name__icontains=query) |
            Q(info_product__icontains=query)
        )

    # Filter berdasarkan process type
    if filter_process:
        ct_qs = ct_qs.filter(process_type_id=filter_process)

    # Tolerance untuk precision floating point - disesuaikan dengan decimal places di database
    TOLERANCE = Decimal('0.01')  # Toleransi 0.01 untuk mengakomodasi rounding di database
    
    # Hitung outdated count dengan precision yang konsisten
    outdated_count = 0
    all_cycle_times = CycleTime.objects.select_related('process_type').all()
    
    for ct in all_cycle_times:
        expected_cost = ct.process_type.rate * ct.hours
        if abs(ct.cost - expected_cost) > TOLERANCE:
            outdated_count += 1

    # Filter berdasarkan status (manual filtering karena calculated field)
    if filter_status:
        ct_list = []
        for ct in ct_qs:
            expected_cost = ct.process_type.rate * ct.hours
            is_outdated = abs(ct.cost - expected_cost) > TOLERANCE
            
            if filter_status == 'outdated' and is_outdated:
                ct_list.append(ct)
            elif filter_status == 'sesuai' and not is_outdated:
                ct_list.append(ct)
        
        # Manual pagination untuk filtered list
        paginator = Paginator(ct_list, 10)
        page_number = request.GET.get('page')
        items = paginator.get_page(page_number)
    else:
        # Normal pagination untuk queryset
        paginator = Paginator(ct_qs, 10)
        page_number = request.GET.get('page')
        items = paginator.get_page(page_number)

    # Status untuk setiap item dengan precision yang sama
    for item in items:
        expected_cost = item.process_type.rate * item.hours
        item.expected_cost = expected_cost
        item.is_outdated = abs(item.cost - expected_cost) > TOLERANCE
        item.status_badge = 'bg-warning' if item.is_outdated else 'bg-success'
        item.status_text = 'Perlu Update' if item.is_outdated else 'Sesuai'

    # Opsi untuk dropdown process type
    process_options = Process.objects.all().order_by('name')
    
    # Get process name for display in filter info
    filter_process_name = ""
    if filter_process:
        try:
            process_obj = Process.objects.get(id=filter_process)
            filter_process_name = process_obj.name
        except Process.DoesNotExist:
            pass

    context = {
        'items': items,
        'query': query,
        'filter_process': filter_process,
        'filter_process_name': filter_process_name,
        'filter_status': filter_status,
        'process_options': process_options,
        'active_menu': 'cycle_time',
        'outdated_count': outdated_count,
    }

    return render(request, 'cycletime/list.html', context)

def cycletime_pdf(request):
    # Ambil semua parameter filter dari request
    query = request.GET.get('q', '')
    filter_process = request.GET.get('process', '')
    filter_status = request.GET.get('status', '')

    cycle_times = CycleTime.objects.select_related(
        'process_type', 'od_thickness', 'ct_for'
    ).order_by(
        'process_type__name', 'od_thickness', 'ct_for'
    )

    # Terapkan filter pencarian
    if query:
        cycle_times = cycle_times.filter(
            Q(process_type__name__icontains=query) |
            Q(od_thickness__size__icontains=query) |
            Q(ct_for__name__icontains=query) |
            Q(info_product__icontains=query)
        )

    if filter_process:
        cycle_times = cycle_times.filter(process_type_id=filter_process)

    # Tolerance untuk precision floating point
    TOLERANCE = Decimal('0.01')

    # Convert to list dan add status information
    cycle_times_list = []
    sesuai_count = 0
    outdated_count = 0

    for ct in cycle_times:
        expected_cost = ct.process_type.rate * ct.hours
        is_outdated = abs(ct.cost - expected_cost) > TOLERANCE
        ct.is_outdated = is_outdated

        # Filter berdasarkan status
        if filter_status == 'outdated' and not is_outdated:
            continue
        elif filter_status == 'sesuai' and is_outdated:
            continue

        cycle_times_list.append(ct)

        if is_outdated:
            outdated_count += 1
        else:
            sesuai_count += 1

    today = date.today()

    # Buat informasi filter untuk ditampilkan di PDF
    filter_info = []
    if query:
        filter_info.append(f"Pencarian: {query}")
    if filter_process:
        try:
            process_obj = Process.objects.get(id=filter_process)
            filter_info.append(f"Process: {process_obj.name}")
        except Process.DoesNotExist:
            pass
    if filter_status:
        status_names = {
            'sesuai': 'Sesuai Rate',
            'outdated': 'Perlu Update'
        }
        filter_info.append(f"Status: {status_names.get(filter_status, filter_status)}")

    template_path = 'cycletime/pdf.html'
    context = {
        'cycle_times': cycle_times_list,
        'today': today,
        'filter_info': filter_info,
        'has_filters': bool(query or filter_process or filter_status),
        'sesuai_count': sesuai_count,
        'outdated_count': outdated_count,
    }

    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="cycle_time_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)

    return response

def cycletime_add(request):
    processes = Process.objects.all()
    grades = MaterialGrade.objects.all()
    
    # Initialize odthicknesses as empty queryset
    odthicknesses = OdThickness.objects.none()

    if request.method == 'POST':
        try:
            process_type_id = request.POST.get('process_type')
            od_thickness = request.POST.get('od_thickness')
            ct_for = request.POST.get('ct_for')
            hours = request.POST.get('hours')
            info_product = request.POST.get('info_product')

            # Validasi input
            if not all([process_type_id, od_thickness, ct_for, hours]):
                messages.error(request, 'Semua field wajib diisi kecuali Info Product')
                
                # Jika ada process_type_id, ambil odthicknesses yang sesuai
                if process_type_id:
                    odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                
                return render(request, 'cycletime/add.html', {
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })

            # Validasi bahwa od_thickness sesuai dengan process_type
            od_thickness_obj = OdThickness.objects.get(id=od_thickness)
            if od_thickness_obj.process_type_id != int(process_type_id):
                messages.error(request, "OD Thickness yang dipilih tidak sesuai dengan Process Type.")
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/add.html', {
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })

            # Cek duplikasi berdasarkan kombinasi process_type, od_thickness, dan ct_for
            existing = CycleTime.objects.filter(
                process_type_id=process_type_id,
                od_thickness_id=od_thickness,
                ct_for_id=ct_for
            ).exists()

            if existing:
                messages.error(request, "Cycle Time dengan kombinasi Process Type, OD Thickness, dan Grade ini sudah ada.")
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/add.html', {
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })

            # Dapatkan process dan hitung cost otomatis
            process = Process.objects.get(id=process_type_id)
            
            # Konversi hours ke Decimal dengan error handling
            try:
                hours_decimal = Decimal(str(hours))
            except (InvalidOperation, ValueError):
                messages.error(request, 'Hours harus berupa angka yang valid')
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/add.html', {
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })
            
            # Hitung cost
            if process.rate:
                calculated_cost = process.rate * hours_decimal
            else:
                calculated_cost = Decimal('0')

            CycleTime.objects.create(
                process_type_id=process_type_id,
                od_thickness_id=od_thickness,
                ct_for_id=ct_for,
                hours=hours_decimal,
                cost=calculated_cost,
                info_product=info_product
            )
            
            messages.success(request, 'Cycle Time berhasil ditambahkan')
            return redirect('cycletime_list')
            
        except Process.DoesNotExist:
            messages.error(request, 'Process tidak ditemukan')
        except OdThickness.DoesNotExist:
            messages.error(request, 'OD Thickness tidak ditemukan')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')

        # Jika ada error, tetap tampilkan odthicknesses sesuai process_type
        if process_type_id:
            odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)

    return render(request, 'cycletime/add.html', {
        'processes': processes,
        'odthicknesses': odthicknesses,
        'grades': grades,
        'active_menu': 'cycle_time'
    })


def cycletime_edit(request, pk):
    item = get_object_or_404(CycleTime, pk=pk)
    processes = Process.objects.all()
    grades = MaterialGrade.objects.all()
    
    # Filter odthicknesses berdasarkan process_type dari item yang sedang diedit
    if item.process_type:
        odthicknesses = OdThickness.objects.filter(process_type=item.process_type)
    else:
        odthicknesses = OdThickness.objects.none()

    if request.method == 'POST':
        try:
            process_type_id = request.POST.get('process_type')
            od_thickness = request.POST.get('od_thickness')
            ct_for = request.POST.get('ct_for')
            hours = request.POST.get('hours')
            info_product = request.POST.get('info_product')
            
            # Validasi input
            if not all([process_type_id, od_thickness, ct_for, hours]):
                messages.error(request, 'Semua field wajib diisi kecuali Info Product')
                
                # Filter odthicknesses sesuai dengan process_type yang dipilih
                if process_type_id:
                    odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                
                return render(request, 'cycletime/edit.html', {
                    'item': item,
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })

            # Validasi bahwa od_thickness sesuai dengan process_type
            od_thickness_obj = OdThickness.objects.get(id=od_thickness)
            if od_thickness_obj.process_type_id != int(process_type_id):
                messages.error(request, "OD Thickness yang dipilih tidak sesuai dengan Process Type.")
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/edit.html', {
                    'item': item,
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })

            # Cek duplikasi berdasarkan kombinasi process_type, od_thickness, dan ct_for
            # kecuali item yang sedang diedit
            existing = CycleTime.objects.filter(
                process_type_id=process_type_id,
                od_thickness_id=od_thickness,
                ct_for_id=ct_for
            ).exclude(pk=pk).exists()

            if existing:
                messages.error(request, "Cycle Time dengan kombinasi Process Type, OD Thickness, dan Grade ini sudah ada.")
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/edit.html', {
                    'item': item,
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })
            
            # Dapatkan process dan hitung cost otomatis
            process = Process.objects.get(id=process_type_id)
            
            # Konversi hours ke Decimal dengan error handling
            try:
                hours_decimal = Decimal(str(hours))
            except (InvalidOperation, ValueError):
                messages.error(request, 'Hours harus berupa angka yang valid')
                odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'cycletime/edit.html', {
                    'item': item,
                    'processes': processes,
                    'odthicknesses': odthicknesses,
                    'grades': grades,
                    'active_menu': 'cycle_time',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness,
                    'selected_ct_for': ct_for,
                    'hours': hours,
                    'info_product': info_product
                })
            
            # Hitung cost
            if process.rate:
                calculated_cost = process.rate * hours_decimal
            else:
                calculated_cost = Decimal('0')

            # Update item
            item.process_type_id = process_type_id
            item.od_thickness_id = od_thickness
            item.ct_for_id = ct_for
            item.hours = hours_decimal
            item.cost = calculated_cost
            item.info_product = info_product
            item.save()
            
            messages.success(request, 'Cycle Time berhasil diupdate')
            return redirect('cycletime_list')
            
        except Process.DoesNotExist:
            messages.error(request, 'Process tidak ditemukan')
        except OdThickness.DoesNotExist:
            messages.error(request, 'OD Thickness tidak ditemukan')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')

        # Jika ada error, tetap tampilkan odthicknesses sesuai process_type
        if process_type_id:
            odthicknesses = OdThickness.objects.filter(process_type_id=process_type_id)

    return render(request, 'cycletime/edit.html', {
        'item': item,
        'processes': processes,
        'odthicknesses': odthicknesses,
        'grades': grades,
        'active_menu': 'cycle_time'
    })
    
def cycletime_delete(request, id):
    """
    View untuk menghapus Cycle Time
    """
    if request.method == 'POST':
        try:
            cycletime = get_object_or_404(CycleTime, id=id)
            
            # Simpan informasi untuk pesan
            cycle_name = f"{cycletime.process_type.name} - {cycletime.od_thickness} - {cycletime.ct_for}"
            
            cycletime.delete()
            
            messages.success(request, f'Cycle Time "{cycle_name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('cycletime_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Cycle Time: {str(e)}')
            return redirect('cycletime_list')
    
    return redirect('cycletime_list')
    
def shift_list(request):
    query = request.GET.get('q', '')
    
    items = Shift.objects.all().order_by('-created_at')

    if query:
        items = items.filter(
            Q(name__icontains=query) |
            Q(remarks__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'active_menu': 'shift',
    }
    return render(request, 'shift/list.html', context)

def shift_add(request):
    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            remarks = request.POST.get('remarks', '').strip()

            # Validasi wajib
            if not name:
                messages.error(request, "Nama Shift wajib diisi.")
                return render(request, 'shift/add.html', {
                    'active_menu': 'shift',
                    'name': name,
                    'remarks': remarks
                })

            Shift.objects.create(name=name, remarks=remarks)
            
            messages.success(request, "Shift berhasil ditambahkan.")
            return redirect('shift_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Shift: {str(e)}')
            return render(request, 'shift/add.html', {
                'active_menu': 'shift'
            })

    return render(request, 'shift/add.html', {
        'active_menu': 'shift'
    })


def shift_edit(request, pk):
    item = get_object_or_404(Shift, pk=pk)

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            remarks = request.POST.get('remarks', '').strip()

            # Validasi wajib diisi
            if not name:
                messages.error(request, "Nama Shift wajib diisi.")
                return render(request, 'shift/edit.html', {
                    'item': item,
                    'active_menu': 'shift'
                })

            # Update data
            item.name = name
            item.remarks = remarks
            item.save()

            messages.success(request, "Shift berhasil diperbarui.")
            return redirect('shift_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Shift: {str(e)}')
            return render(request, 'shift/edit.html', {
                'item': item,
                'active_menu': 'shift'
            })

    return render(request, 'shift/edit.html', {
        'item': item,
        'active_menu': 'shift'
    })
    
def shift_delete(request, id):
    """
    View untuk menghapus Shift
    """
    if request.method == 'POST':
        try:
            shift = get_object_or_404(Shift, id=id)
            
            # Simpan nama untuk pesan
            shift_name = shift.name
            
            shift.delete()
            
            messages.success(request, f'Shift "{shift_name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('shift_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Shift: {str(e)}')
            return redirect('shift_list')
    
    return redirect('shift_list')
    
def operator_list(request):
    query = request.GET.get('q', '')
    
    items = Operator.objects.all().order_by('-created_at')

    if query:
        items = items.filter(
            Q(employee_id__icontains=query) |
            Q(initial__icontains=query) |
            Q(name__icontains=query) |
            Q(position__icontains=query) |
            Q(work_station__icontains=query) |
            Q(remarks__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)

    context = {
        'items': items,
        'query': query,
        'active_menu': 'operator',
    }
    return render(request, 'operator/list.html', context)


def operator_add(request):
    # Ambil pilihan dari model
    work_stations = Operator._meta.get_field('work_station').choices
    positions = Operator._meta.get_field('position').choices

    if request.method == 'POST':
        try:
            employee_id = request.POST.get('employee_id', '').strip()
            initial = request.POST.get('initial', '').strip()
            name = request.POST.get('name', '').strip()
            position = request.POST.get('position', '').strip()
            work_station = request.POST.get('work_station', '').strip()
            remarks = request.POST.get('remarks', '').strip()

            # Validasi wajib
            if not name:
                messages.error(request, "Nama wajib diisi.")
                return render(request, 'operator/add.html', {
                    'work_stations': work_stations,
                    'positions': positions,
                    'active_menu': 'operator',
                    'employee_id': employee_id,
                    'initial': initial,
                    'name': name,
                    'position': position,
                    'work_station': work_station,
                    'remarks': remarks
                })

            # Validasi duplikat Employee ID (jika diisi)
            if employee_id and Operator.objects.filter(employee_id=employee_id).exists():
                messages.error(request, f"Employee ID '{employee_id}' sudah ada. Silakan gunakan Employee ID yang berbeda.")
                return render(request, 'operator/add.html', {
                    'work_stations': work_stations,
                    'positions': positions,
                    'active_menu': 'operator',
                    'employee_id': employee_id,
                    'initial': initial,
                    'name': name,
                    'position': position,
                    'work_station': work_station,
                    'remarks': remarks
                })

            Operator.objects.create(
                employee_id=employee_id if employee_id else None,
                initial=initial if initial else None,
                name=name,
                position=position if position else None,
                work_station=work_station if work_station else None,
                remarks=remarks if remarks else None
            )
            
            messages.success(request, "Operator berhasil ditambahkan.")
            return redirect('operator_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Operator: {str(e)}')
            return render(request, 'operator/add.html', {
                'work_stations': work_stations,
                'positions': positions,
                'active_menu': 'operator'
            })

    return render(request, 'operator/add.html', {
        'work_stations': work_stations,
        'positions': positions,
        'active_menu': 'operator'
    })


def operator_edit(request, pk):
    item = get_object_or_404(Operator, pk=pk)
    work_stations = Operator._meta.get_field('work_station').choices
    positions = Operator._meta.get_field('position').choices

    if request.method == 'POST':
        try:
            employee_id = request.POST.get('employee_id', '').strip()
            initial = request.POST.get('initial', '').strip()
            name = request.POST.get('name', '').strip()
            position = request.POST.get('position', '').strip()
            work_station = request.POST.get('work_station', '').strip()
            remarks = request.POST.get('remarks', '').strip()

            # Validasi wajib diisi
            if not name:
                messages.error(request, "Nama wajib diisi.")
                return render(request, 'operator/edit.html', {
                    'item': item,
                    'work_stations': work_stations,
                    'positions': positions,
                    'active_menu': 'operator'
                })

            # Validasi duplikat Employee ID (jika diisi dan berbeda dari yang sekarang)
            if employee_id and employee_id != item.employee_id:
                if Operator.objects.filter(employee_id=employee_id).exclude(pk=pk).exists():
                    messages.error(request, f"Employee ID '{employee_id}' sudah ada. Silakan gunakan Employee ID yang berbeda.")
                    return render(request, 'operator/edit.html', {
                        'item': item,
                        'work_stations': work_stations,
                        'positions': positions,
                        'active_menu': 'operator'
                    })

            # Update data
            item.employee_id = employee_id if employee_id else None
            item.initial = initial if initial else None
            item.name = name
            item.position = position if position else None
            item.work_station = work_station if work_station else None
            item.remarks = remarks if remarks else None
            item.save()

            messages.success(request, "Operator berhasil diperbarui.")
            return redirect('operator_list')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Operator: {str(e)}')
            return render(request, 'operator/edit.html', {
                'item': item,
                'work_stations': work_stations,
                'positions': positions,
                'active_menu': 'operator'
            })

    return render(request, 'operator/edit.html', {
        'item': item,
        'work_stations': work_stations,
        'positions': positions,
        'active_menu': 'operator'
    })


def operator_delete(request, id):
    """
    View untuk menghapus Operator
    """
    if request.method == 'POST':
        try:
            operator = get_object_or_404(Operator, id=id)
            
            # Simpan nama untuk pesan
            operator_name = operator.name
            
            operator.delete()
            
            messages.success(request, f'Operator "{operator_name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('operator_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Operator: {str(e)}')
            return redirect('operator_list')
    
    return redirect('operator_list')

def pricebook_list(request):
    query = request.GET.get('q', '')
    filter_process = request.GET.get('process', '')
    filter_pb_for = request.GET.get('pb_for', '')
    filter_status = request.GET.get('status', '')
    
    pb_qs = PriceBook.objects.select_related('process_type', 'od_thickness', 'pb_for').order_by('-created_at')

    # Filter pencarian
    if query:
        pb_qs = pb_qs.filter(
            Q(process_type__name__icontains=query) |
            Q(od_thickness__size__icontains=query) |
            Q(pb_for__name__icontains=query) |
            Q(remarks__icontains=query)
        )

    # Filter berdasarkan process type
    if filter_process:
        pb_qs = pb_qs.filter(process_type_id=filter_process)

    # Filter berdasarkan pb_for
    if filter_pb_for:
        pb_qs = pb_qs.filter(pb_for_id=filter_pb_for)

    # Tolerance untuk precision floating point
    TOLERANCE = Decimal('0.01')
    
    # Hitung outdated count dengan precision yang konsisten
    outdated_count = 0
    all_price_books = PriceBook.objects.select_related('process_type').all()
    
    for pb in all_price_books:
        if pb.process_type and pb.time_in_h and pb.process_type.rate:
            # Hitung expected costs
            expected_cost_per_end = pb.process_type.rate * pb.time_in_h
            expected_cost_per_joint = expected_cost_per_end * 2
            expected_cost_vtl = expected_cost_per_end
            
            # Check jika ada perbedaan dengan tolerance
            is_outdated = (
                (pb.cost_per_end and abs(pb.cost_per_end - expected_cost_per_end) > TOLERANCE) or
                (pb.cost_per_joint and abs(pb.cost_per_joint - expected_cost_per_joint) > TOLERANCE) or
                (pb.cost_vtl and abs(pb.cost_vtl - expected_cost_vtl) > TOLERANCE)
            )
            
            if is_outdated:
                outdated_count += 1

    # Filter berdasarkan status (manual filtering karena calculated field)
    if filter_status:
        pb_list = []
        for pb in pb_qs:
            if pb.process_type and pb.time_in_h and pb.process_type.rate:
                expected_cost_per_end = pb.process_type.rate * pb.time_in_h
                expected_cost_per_joint = expected_cost_per_end * 2
                expected_cost_vtl = expected_cost_per_end
                
                is_outdated = (
                    (pb.cost_per_end and abs(pb.cost_per_end - expected_cost_per_end) > TOLERANCE) or
                    (pb.cost_per_joint and abs(pb.cost_per_joint - expected_cost_per_joint) > TOLERANCE) or
                    (pb.cost_vtl and abs(pb.cost_vtl - expected_cost_vtl) > TOLERANCE)
                )
            else:
                is_outdated = False
            
            if filter_status == 'outdated' and is_outdated:
                pb_list.append(pb)
            elif filter_status == 'sesuai' and not is_outdated:
                pb_list.append(pb)
        
        # Manual pagination untuk filtered list
        paginator = Paginator(pb_list, 10)
        page_number = request.GET.get('page')
        items = paginator.get_page(page_number)
    else:
        # Normal pagination untuk queryset
        paginator = Paginator(pb_qs, 10)
        page_number = request.GET.get('page')
        items = paginator.get_page(page_number)

    # Status untuk setiap item dengan precision yang sama
    for item in items:
        item.is_outdated = False
        item.status_badge = 'bg-success'
        item.status_text = 'Sesuai'
        
        if item.process_type and item.time_in_h and item.process_type.rate:
            expected_cost_per_end = item.process_type.rate * item.time_in_h
            expected_cost_per_joint = expected_cost_per_end * 2
            expected_cost_vtl = expected_cost_per_end
            
            is_outdated = (
                (item.cost_per_end and abs(item.cost_per_end - expected_cost_per_end) > TOLERANCE) or
                (item.cost_per_joint and abs(item.cost_per_joint - expected_cost_per_joint) > TOLERANCE) or
                (item.cost_vtl and abs(item.cost_vtl - expected_cost_vtl) > TOLERANCE)
            )
            
            if is_outdated:
                item.is_outdated = True
                item.status_badge = 'bg-warning'
                item.status_text = 'Perlu Update'

    # Opsi untuk dropdown process type dan material grade
    process_options = Process.objects.all().order_by('name')
    material_grade_options = MaterialGrade.objects.all().order_by('name')
    
    # Get names for display in filter info
    filter_process_name = ""
    filter_pb_for_name = ""
    
    if filter_process:
        try:
            process_obj = Process.objects.get(id=filter_process)
            filter_process_name = process_obj.name
        except Process.DoesNotExist:
            pass
    
    if filter_pb_for:
        try:
            pb_for_obj = MaterialGrade.objects.get(id=filter_pb_for)
            filter_pb_for_name = pb_for_obj.name
        except MaterialGrade.DoesNotExist:
            pass

    context = {
        'items': items,
        'query': query,
        'filter_process': filter_process,
        'filter_process_name': filter_process_name,
        'filter_pb_for': filter_pb_for,
        'filter_pb_for_name': filter_pb_for_name,
        'filter_status': filter_status,
        'process_options': process_options,
        'material_grade_options': material_grade_options,
        'active_menu': 'price_book',
        'outdated_count': outdated_count,
    }

    return render(request, 'pricebook/list.html', context)

def pricebook_pdf(request):
    # Ambil semua parameter filter dari request
    query = request.GET.get('q', '')
    filter_process = request.GET.get('process', '')
    filter_pb_for = request.GET.get('pb_for', '')
    filter_status = request.GET.get('status', '')

    price_books = PriceBook.objects.select_related(
        'process_type', 'od_thickness', 'pb_for'
    ).order_by(
        'process_type__name', 'od_thickness__size', 'pb_for__name'
    )

    # Terapkan filter pencarian
    if query:
        price_books = price_books.filter(
            Q(process_type__name__icontains=query) |
            Q(od_thickness__size__icontains=query) |
            Q(pb_for__name__icontains=query) |
            Q(remarks__icontains=query)
        )

    if filter_process:
        price_books = price_books.filter(process_type_id=filter_process)

    if filter_pb_for:
        price_books = price_books.filter(pb_for_id=filter_pb_for)

    # Tolerance untuk precision floating point
    TOLERANCE = Decimal('0.01')

    # Convert to list dan add status information
    price_books_list = []
    sesuai_count = 0
    outdated_count = 0

    for pb in price_books:
        if pb.process_type and pb.time_in_h and pb.process_type.rate:
            expected_cost_per_end = pb.process_type.rate * pb.time_in_h
            expected_cost_per_joint = expected_cost_per_end * 2
            expected_cost_vtl = expected_cost_per_end
            
            is_outdated = (
                (pb.cost_per_end and abs(pb.cost_per_end - expected_cost_per_end) > TOLERANCE) or
                (pb.cost_per_joint and abs(pb.cost_per_joint - expected_cost_per_joint) > TOLERANCE) or
                (pb.cost_vtl and abs(pb.cost_vtl - expected_cost_vtl) > TOLERANCE)
            )
        else:
            is_outdated = False
        
        pb.is_outdated = is_outdated

        # Filter berdasarkan status
        if filter_status == 'outdated' and not is_outdated:
            continue
        elif filter_status == 'sesuai' and is_outdated:
            continue

        price_books_list.append(pb)

        if is_outdated:
            outdated_count += 1
        else:
            sesuai_count += 1

    today = date.today()

    # Buat informasi filter untuk ditampilkan di PDF
    filter_info = []
    if query:
        filter_info.append(f"Pencarian: {query}")
    if filter_process:
        try:
            process_obj = Process.objects.get(id=filter_process)
            filter_info.append(f"Process: {process_obj.name}")
        except Process.DoesNotExist:
            pass
    if filter_pb_for:
        try:
            pb_for_obj = MaterialGrade.objects.get(id=filter_pb_for)
            filter_info.append(f"Material Grade: {pb_for_obj.name}")
        except MaterialGrade.DoesNotExist:
            pass
    if filter_status:
        status_names = {
            'sesuai': 'Sesuai Rate',
            'outdated': 'Perlu Update'
        }
        filter_info.append(f"Status: {status_names.get(filter_status, filter_status)}")

    template_path = 'pricebook/pdf.html'
    context = {
        'price_books': price_books_list,
        'today': today,
        'filter_info': filter_info,
        'has_filters': bool(query or filter_process or filter_pb_for or filter_status),
        'sesuai_count': sesuai_count,
        'outdated_count': outdated_count,
    }

    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="price_book_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)

    return response

def pricebook_add(request):
    processes = Process.objects.all()
    material_grades = MaterialGrade.objects.all()
    
    # Initialize od_thicknesses as empty queryset
    od_thicknesses = OdThickness.objects.none()

    if request.method == 'POST':
        try:
            process_type_id = request.POST.get('process_type')
            od_thickness_id = request.POST.get('od_thickness')
            pb_for_id = request.POST.get('pb_for')
            time_in_h = request.POST.get('time_in_h')
            remarks = request.POST.get('remarks')

            # Validasi wajib
            if not process_type_id or not od_thickness_id:
                messages.error(request, "Process Type dan OD Thickness wajib dipilih.")
                
                # Jika ada process_type_id, ambil od_thicknesses yang sesuai
                if process_type_id:
                    od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                
                return render(request, 'pricebook/add.html', {
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Dapatkan objects
            process_type = Process.objects.get(id=process_type_id)
            od_thickness = OdThickness.objects.get(id=od_thickness_id)
            pb_for = MaterialGrade.objects.get(id=pb_for_id) if pb_for_id else None

            # Validasi bahwa od_thickness sesuai dengan process_type
            if od_thickness.process_type_id != int(process_type_id):
                messages.error(request, "OD Thickness yang dipilih tidak sesuai dengan Process Type.")
                od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'pricebook/add.html', {
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Cek duplikasi berdasarkan kombinasi process_type, od_thickness, dan pb_for
            existing = PriceBook.objects.filter(
                process_type=process_type,
                od_thickness=od_thickness,
                pb_for=pb_for
            ).exists()

            if existing:
                messages.error(request, "Price Book dengan kombinasi Process Type, OD Thickness, dan Material Grade ini sudah ada.")
                od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'pricebook/add.html', {
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Hitung costs otomatis jika time_in_h dan rate tersedia
            cost_per_end = None
            cost_per_joint = None
            cost_vtl = None
            
            if time_in_h and process_type.rate:
                try:
                    time_decimal = Decimal(str(time_in_h))
                    # Rumus: Cost Per End = time × rate
                    cost_per_end = process_type.rate * time_decimal
                    # Rumus: Cost Per Joint = end × 2
                    cost_per_joint = cost_per_end * 2
                    # Rumus: Cost VTL = time × rate (sama dengan Cost Per End)
                    cost_vtl = cost_per_end
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Time harus berupa angka yang valid')
                    od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                    return render(request, 'pricebook/add.html', {
                        'processes': processes,
                        'od_thicknesses': od_thicknesses,
                        'material_grades': material_grades,
                        'active_menu': 'price_book',
                        'selected_process': process_type_id,
                        'selected_od_thickness': od_thickness_id,
                        'selected_pb_for': pb_for_id,
                        'time_in_h': time_in_h,
                        'remarks': remarks
                    })

            PriceBook.objects.create(
                process_type=process_type,
                od_thickness=od_thickness,
                pb_for=pb_for,
                time_in_h=time_in_h or None,
                cost_per_end=cost_per_end,
                cost_per_joint=cost_per_joint,
                cost_vtl=cost_vtl,
                remarks=remarks
            )

            messages.success(request, "Price Book berhasil ditambahkan.")
            return redirect('pricebook_list')
            
        except Process.DoesNotExist:
            messages.error(request, 'Process tidak ditemukan')
        except OdThickness.DoesNotExist:
            messages.error(request, 'OD Thickness tidak ditemukan')
        except MaterialGrade.DoesNotExist:
            messages.error(request, 'Material Grade tidak ditemukan')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')

        # Jika ada error, tetap tampilkan od_thicknesses sesuai process_type
        if process_type_id:
            od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)

    context = {
        'processes': processes,
        'od_thicknesses': od_thicknesses,
        'material_grades': material_grades,
        'active_menu': 'price_book'
    }
    return render(request, 'pricebook/add.html', context)


# Tambahkan view AJAX untuk mengambil OD Thickness berdasarkan Process Type
def get_od_thickness_by_process(request):
    """
    AJAX view untuk mengambil OD Thickness berdasarkan Process Type yang dipilih
    """
    if request.method == 'GET':
        process_type_id = request.GET.get('process_type_id')
        
        if process_type_id:
            od_thicknesses = OdThickness.objects.filter(
                process_type_id=process_type_id
            ).order_by('size')
            
            data = [
                {
                    'id': od.id,
                    'text': f"{od.size} (OD: {od.od}, Wall: {od.wall})"
                }
                for od in od_thicknesses
            ]
            
            return JsonResponse({'od_thicknesses': data})
        
        return JsonResponse({'od_thicknesses': []})

def pricebook_edit(request, pk):
    item = get_object_or_404(PriceBook, pk=pk)
    processes = Process.objects.all()
    material_grades = MaterialGrade.objects.all()
    
    # Filter od_thicknesses berdasarkan process_type dari item yang sedang diedit
    if item.process_type:
        od_thicknesses = OdThickness.objects.filter(process_type=item.process_type)
    else:
        od_thicknesses = OdThickness.objects.none()

    if request.method == 'POST':
        try:
            process_type_id = request.POST.get('process_type')
            od_thickness_id = request.POST.get('od_thickness')
            pb_for_id = request.POST.get('pb_for')
            time_in_h = request.POST.get('time_in_h')
            remarks = request.POST.get('remarks')

            # Validasi wajib diisi
            if not process_type_id or not od_thickness_id:
                messages.error(request, "Process Type dan OD Thickness wajib dipilih.")
                
                # Filter od_thicknesses sesuai dengan process_type yang dipilih
                if process_type_id:
                    od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                
                return render(request, 'pricebook/edit.html', {
                    'item': item,
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Dapatkan objects
            process_type = Process.objects.get(id=process_type_id)
            od_thickness = OdThickness.objects.get(id=od_thickness_id)
            pb_for = MaterialGrade.objects.get(id=pb_for_id) if pb_for_id else None

            # Validasi bahwa od_thickness sesuai dengan process_type
            if od_thickness.process_type_id != int(process_type_id):
                messages.error(request, "OD Thickness yang dipilih tidak sesuai dengan Process Type.")
                od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'pricebook/edit.html', {
                    'item': item,
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Cek duplikasi berdasarkan kombinasi process_type, od_thickness, dan pb_for
            # kecuali item yang sedang diedit
            existing = PriceBook.objects.filter(
                process_type=process_type,
                od_thickness=od_thickness,
                pb_for=pb_for
            ).exclude(pk=pk).exists()

            if existing:
                messages.error(request, "Price Book dengan kombinasi Process Type, OD Thickness, dan Material Grade ini sudah ada.")
                od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                return render(request, 'pricebook/edit.html', {
                    'item': item,
                    'processes': processes,
                    'od_thicknesses': od_thicknesses,
                    'material_grades': material_grades,
                    'active_menu': 'price_book',
                    'selected_process': process_type_id,
                    'selected_od_thickness': od_thickness_id,
                    'selected_pb_for': pb_for_id,
                    'time_in_h': time_in_h,
                    'remarks': remarks
                })

            # Update basic fields
            item.process_type = process_type
            item.od_thickness = od_thickness
            item.pb_for = pb_for
            item.time_in_h = time_in_h or None
            item.remarks = remarks

            # Hitung costs otomatis jika time_in_h dan rate tersedia
            if time_in_h and item.process_type.rate:
                try:
                    time_decimal = Decimal(str(time_in_h))
                    # Rumus: Cost Per End = time × rate
                    item.cost_per_end = item.process_type.rate * time_decimal
                    # Rumus: Cost Per Joint = end × 2
                    item.cost_per_joint = item.cost_per_end * 2
                    # Rumus: Cost VTL = time × rate (sama dengan Cost Per End)
                    item.cost_vtl = item.cost_per_end
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Time harus berupa angka yang valid')
                    od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)
                    return render(request, 'pricebook/edit.html', {
                        'item': item,
                        'processes': processes,
                        'od_thicknesses': od_thicknesses,
                        'material_grades': material_grades,
                        'active_menu': 'price_book',
                        'selected_process': process_type_id,
                        'selected_od_thickness': od_thickness_id,
                        'selected_pb_for': pb_for_id,
                        'time_in_h': time_in_h,
                        'remarks': remarks
                    })
            else:
                # Jika tidak ada time atau rate, set costs ke None
                item.cost_per_end = None
                item.cost_per_joint = None
                item.cost_vtl = None

            item.save()

            messages.success(request, "Price Book berhasil diperbarui.")
            return redirect('pricebook_list')
                
        except Process.DoesNotExist:
            messages.error(request, 'Process tidak ditemukan')
        except OdThickness.DoesNotExist:
            messages.error(request, 'OD Thickness tidak ditemukan')
        except MaterialGrade.DoesNotExist:
            messages.error(request, 'Material Grade tidak ditemukan')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')
            
        # Jika ada error, tetap tampilkan od_thicknesses sesuai process_type
        if process_type_id:
            od_thicknesses = OdThickness.objects.filter(process_type_id=process_type_id)

    context = {
        'item': item,
        'processes': processes,
        'od_thicknesses': od_thicknesses,
        'material_grades': material_grades,
        'active_menu': 'price_book'
    }
    return render(request, 'pricebook/edit.html', context)

def pricebook_delete(request, id):
    """
    View untuk menghapus Price Book
    """
    if request.method == 'POST':
        try:
            pricebook = get_object_or_404(PriceBook, id=id)
            
            # Simpan informasi untuk pesan
            pb_name = f"{pricebook.process_type.name} - {pricebook.od_thickness.size}"
            if pricebook.pb_for:
                pb_name += f" - {pricebook.pb_for.name}"
            
            pricebook.delete()
            
            messages.success(request, f'Price Book "{pb_name}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('pricebook_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Price Book: {str(e)}')
            return redirect('pricebook_list')
    
    return redirect('pricebook_list')


def thread_report(request, header_id):

    header = get_object_or_404(ThreadHeader, pk=header_id)
    
    # Untuk shift 2 yang melewati tengah malam, kita perlu adjust ordering
    # Jika start_time < 12:00, anggap sebagai hari berikutnya
    detail_list = ThreadDetail.objects.filter(Reff=header).annotate(
        adjusted_time=Case(
            # Jika waktu mulai antara 00:00-11:59, tambahkan 24 jam untuk sorting
            When(start_time__hour__lt=12, then=F('start_time__hour') + 24),
            default=F('start_time__hour'),
        )
    ).order_by('adjusted_time', 'start_time__minute', 'id')
    
    def calculate_actual_hours_from_details():
        total_hours = 0
        for detail in detail_list:
            if detail.start_time and detail.stop_time:
                hours = calculate_time_duration(detail.start_time, detail.stop_time)
                if hours is not None:
                    total_hours += hours
        return total_hours
    
    actual_hours = calculate_actual_hours_from_details()
    
    total_output = detail_list.aggregate(Sum('output'))['output__sum'] or 0
    total_output = round(float(total_output), 2)  # Output tetap 2 desimal
    
    reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
    consumable = ThreadConsumsion.objects.filter(Reff=header).first()
    
    is_shift_1 = header.shift and ('1' in header.shift.name or 'satu' in header.shift.name.lower() or 'first' in header.shift.name.lower())
    is_shift_2 = header.shift and ('2' in header.shift.name or 'dua' in header.shift.name.lower() or 'second' in header.shift.name.lower())
    
    maintenance_duration = 0
    maintenance_info = ""
    
    if reason_stops and reason_stops.maintenance:
        raw_duration = reason_stops.maintenance.duration
        maintenance_duration = float(raw_duration) if raw_duration else 0
        # Round ke 1 desimal untuk konsisten dengan OEE report
        maintenance_duration = round(maintenance_duration, 1)
        
        maintenance_issue = reason_stops.maintenance.issue if reason_stops.maintenance.issue else "Maintenance"
        maintenance_info = f"{maintenance_issue} ({maintenance_duration}h)"
    
    def safe_float(value):
        if value is None or value == '' or value == '-':
            return 0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0
    
    # Semua round ke 1 desimal
    wait_material = round(safe_float(reason_stops.waiting_materials if reason_stops else 0), 1)
    meetings = round(safe_float(reason_stops.meeting if reason_stops else 0), 1)
    breakdown = maintenance_duration  # Sudah 1 desimal
    change_over = round(safe_float(reason_stops.change_over if reason_stops else 0), 1)  # CHANGED: others -> change_over
    total_non_recordable = wait_material + meetings + breakdown + change_over
    total_non_recordable = round(total_non_recordable, 1)
    
    booked_hours = 0
    if header.booked_hours and header.booked_hours.duration:
        booked_hours = float(header.booked_hours.duration)
    booked_hours = round(booked_hours, 1)
    
    total_hours = actual_hours + total_non_recordable
    total_hours = round(total_hours, 1)
    
    # Round actual_hours ke 1 desimal SETELAH perhitungan total_hours
    actual_hours = round(actual_hours, 1)
    
    rejects = round(safe_float(reason_stops.reject if reason_stops else 0), 1)
    cutbacks = round(safe_float(reason_stops.cutback if reason_stops else 0), 1)
    
    for detail in detail_list:
        detail.duration_minutes = calculate_time_duration(detail.start_time, detail.stop_time)
        
        ncr_record = ThreadNcr.objects.filter(serial=detail).first()
        if ncr_record:
            detail.ncr_status = "NCR"
            detail.ncr_reason = ncr_record.reason
        else:
            detail.ncr_status = "-"
            detail.ncr_reason = ""
    
    total_ncr = sum(1 for detail in detail_list if hasattr(detail, 'ncr_status') and detail.ncr_status == "NCR")
    
    daily_maintenances = Maintenance.objects.filter(machine=header)
    
    summary_data = {
        'total_output_1': total_output if is_shift_1 else '',
        'reject_1': rejects if is_shift_1 else '',
        'cutback_1': cutbacks if is_shift_1 else '',
        'waiting_materials_1': wait_material if is_shift_1 else '',
        'meeting_1': meetings if is_shift_1 else '',
        'prod_time_1': actual_hours if is_shift_1 else '',
        'maintenance_1': breakdown if is_shift_1 else '',
        'change_over_1': change_over if is_shift_1 else '',
        'ncr_1': total_ncr if is_shift_1 else '',
        'total_hours_1': total_hours if is_shift_1 else '',
        'total_output_2': total_output if is_shift_2 else '',
        'reject_2': rejects if is_shift_2 else '',
        'cutback_2': cutbacks if is_shift_2 else '',
        'waiting_materials_2': wait_material if is_shift_2 else '',
        'meeting_2': meetings if is_shift_2 else '',
        'prod_time_2': actual_hours if is_shift_2 else '',
        'maintenance_2': breakdown if is_shift_2 else '',
        'change_over_2': change_over if is_shift_2 else '',
        'ncr_2': total_ncr if is_shift_2 else '',
        'total_hours_2': total_hours if is_shift_2 else '',
        'current_shift': header.shift.name if header.shift else '',
        'is_shift_1': is_shift_1,
        'is_shift_2': is_shift_2,
        'maintenance_info': maintenance_info,
        'total_maintenance_duration': breakdown,
        'daily_maintenances': daily_maintenances,
        'correct_actual_hours': actual_hours,
        'total_output': total_output,
        'booked_hours': booked_hours,
        'non_recordable_time': total_non_recordable,
    }
    
    consumable_data = {
        'insert_snmg_1': '',
        'insert_dnmg_1': '',
        'insert_threading_1': '',
        'others_1': '',
        'insert_snmg_2': '',
        'insert_dnmg_2': '',
        'insert_threading_2': '',
        'others_2': '',
    }
    
    if consumable:
        if is_shift_1:
            consumable_data.update({
                'insert_snmg_1': consumable.insert_snmg or '-',
                'insert_dnmg_1': consumable.insert_dnmg or '-',
                'insert_threading_1': consumable.insert_threading or '-',
                'others_1': consumable.others or '-',
            })
        elif is_shift_2:
            consumable_data.update({
                'insert_snmg_2': consumable.insert_snmg or '-',
                'insert_dnmg_2': consumable.insert_dnmg or '-',
                'insert_threading_2': consumable.insert_threading or '-',
                'others_2': consumable.others or '-',
            })
    
    context = {
        'header': header,
        'detail_list': detail_list,
        'summary': summary_data,
        'consumable': consumable_data,
        'reason_stops': reason_stops,
        'consumable_record': consumable,
        'total_ncr': total_ncr,
        'maintenance_records': daily_maintenances,
        'correct_actual_hours': actual_hours,
        'total_output': total_output,
    }
    
    return render(request, 'thread/report.html', context)

@threading_ncr_access_required
def thread_ncr_list(request):
    query = request.GET.get('q', '')
    items = ThreadNcr.objects.select_related(
        'serial__Reff__machine', 
        'serial__bjo'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Thread Header fields - menggunakan field yang benar dari ThreadHeader
            Q(serial__Reff__machine__name__icontains=query) |
            Q(serial__Reff__date__icontains=query) |
            Q(serial__Reff__operator__name__icontains=query) |
            Q(serial__Reff__shift__name__icontains=query) |
            # Job Header fields - menggunakan field yang benar dari JobHeader
            Q(serial__bjo__bjo__icontains=query) |
            Q(serial__bjo__customer__icontains=query) |
            Q(serial__bjo__bt__icontains=query) |
            Q(serial__bjo__product__icontains=query) |
            # Thread Detail fields
            Q(serial__joint_number__icontains=query) |
            # Thread NCR fields
            Q(reason__icontains=query) |
            Q(disposition__icontains=query) |
            Q(action__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'thread_ncr_list',
        
    }
    return render(request, 'thread/ncr/list.html', context)

@threading_ncr_access_required
def thread_ncr_create(request):
    """
    View untuk membuat ThreadNcr secara manual
    """
    if request.method == 'POST':
        try:
            with transaction.atomic():
                serial_id = request.POST.get('serial')
                reason = request.POST.get('reason', '').strip()
                disposition = request.POST.get('disposition', '').strip()
                action = request.POST.get('action', '').strip()

                # Validasi serial (ThreadDetail) wajib
                if not serial_id:
                    messages.error(request, "Thread Detail wajib dipilih.")
                    return redirect('thread_ncr_create')

                try:
                    thread_detail = ThreadDetail.objects.get(id=serial_id)
                except ThreadDetail.DoesNotExist:
                    messages.error(request, "Thread Detail yang dipilih tidak valid.")
                    return redirect('thread_ncr_create')

                # Cek apakah sudah ada NCR untuk thread detail ini
                existing_ncr = ThreadNcr.objects.filter(serial=thread_detail).first()
                if existing_ncr:
                    messages.warning(
                        request, 
                        f"NCR untuk Thread Detail (Joint: {thread_detail.joint_number}) sudah ada. "
                        f"Silakan edit NCR yang sudah ada."
                    )
                    return redirect('thread_ncr_edit', ncr_id=existing_ncr.id)

                # Create ThreadNcr
                thread_ncr = ThreadNcr.objects.create(
                    serial=thread_detail,
                    reason=reason if reason else None,
                    disposition=disposition if disposition else None,
                    action=action if action else None,
                )

                # PERBAIKAN: Update is_ncr flag untuk SEMUA tipe
                if thread_detail.joint_number and thread_detail.bjo:
                    # Update berdasarkan tipe protector
                    if thread_detail.pin_or_box == 'BOX':
                        BoxProtector.objects.filter(
                            serial_number=thread_detail.joint_number, 
                            bjo=thread_detail.bjo
                        ).update(is_ncr=True)
                    elif thread_detail.pin_or_box == 'PIN':
                        PinProtector.objects.filter(
                            serial_number=thread_detail.joint_number, 
                            bjo=thread_detail.bjo
                        ).update(is_ncr=True)
                    
                    # PENTING: Update SerialNumber SELALU, terlepas dari tipe PIN/BOX
                    # Karena joint_number tetap tersimpan di SerialNumber
                    SerialNumber.objects.filter(
                        joint_number=thread_detail.joint_number, 
                        bjo=thread_detail.bjo
                    ).update(is_ncr=True)

                messages.success(
                    request, 
                    f"ThreadNcr berhasil dibuat untuk Joint Number '{thread_detail.joint_number}'. "
                    f"Status NCR pada Serial Number telah diupdate menjadi True."
                )
                return redirect('thread_ncr_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('thread_ncr_create')
    available_details = ThreadDetail.objects.filter(
        threadncr__isnull=True,
        is_uncompleted=False
    ).select_related(
        'Reff__machine',
        'bjo'
    ).order_by('-Reff__date', '-created_at')

    context = {
        'available_details': available_details,
        'active_menu': 'thread_ncr_list',
    }
    return render(request, 'thread/ncr/create.html', context)

@threading_ncr_access_required
def thread_ncr_edit(request, id):
    item = get_object_or_404(ThreadNcr, id=id)
    
    if request.method == 'POST':
        # Update field yang bisa diedit
        item.reason = request.POST.get('reason')
        item.disposition = request.POST.get('disposition')
        item.action = request.POST.get('action')
        
        # Validasi - pastikan setidaknya ada satu field yang diisi
        if not item.reason and not item.disposition and not item.action:
            messages.error(request, "Minimal satu field (Reason, Disposition, atau Action) harus diisi.")
            return redirect('thread_ncr_edit', id=id)
        
        item.save()
        messages.success(request, "Data Threading NCR berhasil diperbarui.")
        return redirect('thread_ncr_list')
    
    return render(request, 'thread/ncr/edit.html', {
        'item': item,
        'active_menu': 'thread/ncr'
    })

@threading_ncr_access_required
def thread_ncr_delete(request, id):
    item = get_object_or_404(ThreadNcr, id=id)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Simpan informasi untuk pesan sebelum menghapus
                thread_info = ""
                if item.serial and item.serial.Reff:
                    machine_name = item.serial.Reff.machine.name if item.serial.Reff.machine else "Unknown"
                    date_str = item.serial.Reff.date.strftime('%d/%m/%Y') if item.serial.Reff.date else "Unknown"
                    thread_info = f"{machine_name} - {date_str}"
                else:
                    thread_info = "Threading NCR"
                
                # Simpan informasi joint number untuk pesan yang lebih informatif
                joint_info = f" (Joint: {item.serial.joint_number})" if item.serial and item.serial.joint_number else ""
                
                # Simpan referensi thread_detail sebelum delete
                thread_detail = item.serial
                
                # PERBAIKAN: Reset is_ncr flag kembali ke False
                if thread_detail and thread_detail.joint_number and thread_detail.bjo:
                    # Reset berdasarkan tipe protector
                    if thread_detail.pin_or_box == 'BOX':
                        BoxProtector.objects.filter(
                            serial_number=thread_detail.joint_number, 
                            bjo=thread_detail.bjo
                        ).update(is_ncr=False)
                    elif thread_detail.pin_or_box == 'PIN':
                        PinProtector.objects.filter(
                            serial_number=thread_detail.joint_number, 
                            bjo=thread_detail.bjo
                        ).update(is_ncr=False)
                    
                    # PENTING: Reset SerialNumber SELALU, terlepas dari tipe PIN/BOX
                    SerialNumber.objects.filter(
                        joint_number=thread_detail.joint_number, 
                        bjo=thread_detail.bjo
                    ).update(is_ncr=False)
                
                # Hapus data NCR
                item.delete()
                
                messages.success(
                    request, 
                    f'Data Threading NCR {thread_info}{joint_info} berhasil dihapus. '
                    f'Status NCR pada Serial Number telah dikembalikan ke normal.'
                )
                return redirect('thread_ncr_list')
                
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('thread_ncr_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('thread_ncr_list')

@threading_consumption_access_required
def thread_consumption_list(request):
    query = request.GET.get('q', '')
    items = ThreadConsumsion.objects.select_related(
        'Reff__machine', 
        'Reff__operator',
        'Reff__shift'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Thread Header fields
            Q(Reff__machine__name__icontains=query) |
            Q(Reff__date__icontains=query) |
            Q(Reff__operator__name__icontains=query) |
            Q(Reff__shift__name__icontains=query) |
            # Thread Consumption fields
            Q(insert_snmg__icontains=query) |
            Q(insert_dnmg__icontains=query) |
            Q(insert_threading__icontains=query) |
            Q(others__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'thread_consumption_list'
    }
    return render(request, 'thread/consumption/list.html', context)

@threading_consumption_access_required
def thread_consumption_edit(request, pk):
    item = get_object_or_404(ThreadConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data - Thread Header tidak bisa diubah, jadi tidak perlu diupdate
            insert_snmg = request.POST.get('insert_snmg') or None
            insert_dnmg = request.POST.get('insert_dnmg') or None
            insert_threading = request.POST.get('insert_threading') or None
            others = request.POST.get('others') or None

            # Update ThreadConsumsion
            item.insert_snmg = insert_snmg
            item.insert_dnmg = insert_dnmg
            item.insert_threading = insert_threading
            item.others = others
            item.save()

            messages.success(request, 'Data Threading Consumption berhasil diperbarui.')
            return redirect('thread_consumption_list')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
    
    context = {
        'item': item,
        'active_menu': 'thread/consumption'
    }
    return render(request, 'thread/consumption/edit.html', context)

@threading_consumption_access_required
def thread_consumption_delete(request, pk):
    item = get_object_or_404(ThreadConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Simpan informasi untuk pesan sebelum menghapus
            thread_info = ""
            if item.Reff:
                machine_name = item.Reff.machine.name if item.Reff.machine else "Unknown"
                date_str = item.Reff.date.strftime('%d/%m/%Y') if item.Reff.date else "Unknown"
                thread_info = f"{machine_name} - {date_str}"
            else:
                thread_info = "Threading Consumption"
            
            # Hapus data
            item.delete()
            
            messages.success(request, f'Data Threading Consumption {thread_info} berhasil dihapus.')
            return redirect('thread_consumption_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('thread_consumption_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('thread_consumption_list')

@welding_access_required
def weld_list(request):
    """List semua WeldHeader dengan filter dan pagination - UPDATED dengan perhitungan total output berdasarkan field output di detail"""
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    headers = WeldHeader.objects.select_related(
        'machine', 'shift', 'operator', 'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    headers = headers.order_by('-date', '-id')
    
    # PERBAIKAN UTAMA: Hitung actual_hours dan total output berdasarkan field output di detail
    for header in headers:
        if not header.is_posted:
            # Jika belum posted, hitung ulang berdasarkan detail terbaru
            detail_qs = WeldDetail.objects.filter(Reff=header)
            total_hours = 0
            total_output = 0
            
            for detail in detail_qs:
                # Hitung total jam
                if detail.start_time and detail.stop_time:
                    duration_hours = calculate_time_duration(detail.start_time, detail.stop_time)
                    if duration_hours:
                        total_hours += duration_hours
                
                # Hitung total output dari field output di detail
                if detail.output:
                    total_output += float(detail.output)
            
            # Update display values dengan nilai yang benar
            header.calculated_actual_hours = round(total_hours, 2)
            header.calculated_actual_output = round(total_output, 2)
        else:
            # Jika sudah posted, gunakan nilai yang sudah disimpan
            header.calculated_actual_hours = float(header.actual_hours) if header.actual_hours else 0
            header.calculated_actual_output = float(header.actual_output) if header.actual_output else 0
    
    paginator = Paginator(headers, 100)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    machine_options = Machine.objects.filter(
        process_type__name__icontains='welding'
    ).values_list('name', flat=True).distinct().order_by('name')

    status_options = [
        ('', '-- All Status --'),
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ]

    context = {
        'headers': page_obj,
        'query': query,
        'filter_machine': filter_machine,
        'filter_date': filter_date,
        'filter_status': filter_status,
        'machine_options': machine_options,
        'status_options': status_options,
        'active_menu': 'weld_list',
    }

    return render(request, 'weld/list.html', context)

@welding_write_access_required
def weld_delete(request, id):
    """Delete WeldHeader - hanya boleh jika belum posted"""
    header = get_object_or_404(WeldHeader, id=id)
    
    if request.method == 'POST':
        try:
            if header.is_posted:
                messages.error(request, 'Data tidak dapat dihapus karena sudah di-posting.')
                return redirect('weld_list')
            
            weld_info = f"{header.machine.name} - {header.date.strftime('%d/%m/%Y')}"
            header.delete()
            
            messages.success(request, f'Record welding {weld_info} berhasil dihapus.')
            return redirect('weld_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('weld_list')
    
    return redirect('weld_list')

@welding_write_access_required
def weld_add(request):
    """Create new WeldHeader record with minimal fields"""
    if request.method == 'POST':
        required_fields = ['date', 'machine', 'shift', 'operator', 'booked_hours']
        missing_fields = [f.replace('_', ' ').title() for f in required_fields if not request.POST.get(f)]

        if missing_fields:
            messages.error(request, f"Field wajib yang belum diisi: {', '.join(missing_fields)}")
        else:
            try:
                try:
                    date_obj = datetime.strptime(request.POST.get('date'), "%Y-%m-%d").date()
                except ValueError:
                    messages.error(request, "Format tanggal tidak valid.")
                    return render(request, 'weld/header.html', get_weld_context_data(request.user))

                try:
                    machine = Machine.objects.get(id=request.POST.get('machine'))
                    shift = Shift.objects.get(id=request.POST.get('shift'))
                    operator = Operator.objects.get(id=request.POST.get('operator'))
                    booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
                except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                    messages.error(request, "Data yang dipilih tidak valid.")
                    return render(request, 'weld/header.html', get_weld_context_data(request.user))

                header = WeldHeader.objects.create(
                    date=date_obj,
                    machine=machine,
                    shift=shift,
                    operator=operator,
                    booked_hours=booked_hours
                )

                messages.success(request, "Welding Record berhasil disimpan.")
                return redirect('weld_detail', header_id=header.pk)

            except Exception as e:
                messages.error(request, f"Terjadi kesalahan: {str(e)}")

    return render(request, 'weld/header.html', get_weld_context_data(request.user))


def get_weld_context_data(user, for_edit=False):
    """Data untuk form Weld Header"""
    # Filter mesin untuk WELDING process
    welding_machines = Machine.objects.filter(
        process_type__name__icontains='welding'
    ).order_by('name')
    
    # Filter operator berdasarkan position = 'WELD'
    welding_operators = Operator.objects.filter(
        position='WELD'
    ).order_by('name')
    
    # Fallback jika tidak ada operator dengan position WELD
    if not welding_operators.exists():
        welding_operators = Operator.objects.all().order_by('name')
    
    # Booked hours logic
    if user.role in ['admin', 'supervisor', 'leadman'] or for_edit:
        booked_hours_list = BookedHours.objects.all().order_by('name')
    else:
        # Operator saat create: hanya 4 opsi utama
        allowed_booked_hours = [
            'FRIDAY NORMAL',
            'FRIDAY OT', 
            'NORMAL',
            'OT'
        ]
        booked_hours_list = BookedHours.objects.filter(
            name__in=allowed_booked_hours
        ).order_by('name')

    return {
        'machine_list': welding_machines,
        'shift_list': Shift.objects.all().order_by('name'),
        'operator_list': welding_operators,
        'booked_hours_list': booked_hours_list,
    }


@welding_write_access_required
def weld_edit(request, header_id):
    """Edit WeldHeader"""
    header = get_object_or_404(WeldHeader, pk=header_id)

    if request.method == 'POST':
        try:
            try:
                date_obj = datetime.strptime(request.POST.get('date'), "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Format tanggal tidak valid.")
                return render(request, 'weld/edit.html', {**get_weld_context_data(request.user, for_edit=True), 'header': header})

            try:
                machine = Machine.objects.get(id=request.POST.get('machine'))
                shift = Shift.objects.get(id=request.POST.get('shift'))
                operator = Operator.objects.get(id=request.POST.get('operator'))
                booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
            except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                messages.error(request, "Data yang dipilih tidak valid.")
                return render(request, 'weld/edit.html', {**get_weld_context_data(request.user, for_edit=True), 'header': header})

            header.date = date_obj
            header.machine = machine
            header.shift = shift
            header.operator = operator
            header.booked_hours = booked_hours
            header.save()

            messages.success(request, "Welding Record berhasil diperbarui.")
            return redirect('weld_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")

    context = get_weld_context_data(request.user, for_edit=True)
    context['header'] = header
    return render(request, 'weld/edit.html', context)

def has_been_reworked(detail):
    """
    Check if a WeldDetail has already been reworked
    Returns True if REWORKED keyword exists in comment
    """
    comment = detail.comment or ''
    return 'REWORKED' in comment.upper()

def update_all_stages_status_on_completion(joint_number, pin_or_box, bjo):
    """
    UPDATE semua UNCOMPLETED stages menjadi COMPLETED ketika ada completion baru
    Dipanggil setiap kali ada stage COMPLETED ditambahkan
    """
    # Ambil semua UNCOMPLETED details untuk joint ini
    uncompleted_details = WeldDetail.objects.filter(
        bjo=bjo,
        joint_number=joint_number,
        pin_or_box=pin_or_box,
        is_uncompleted=True
    ).order_by('created_at')
    
    # Update semua menjadi COMPLETED
    for detail in uncompleted_details:
        old_comment = detail.comment or ''
        
        # Update comment
        if old_comment.startswith('UNCOMPLETED'):
            new_comment = old_comment.replace('UNCOMPLETED', 'COMPLETED', 1)
        elif 'UNCOMPLETED' in old_comment:
            new_comment = old_comment.replace('UNCOMPLETED', 'COMPLETED')
        else:
            new_comment = f"COMPLETED | {old_comment}" if old_comment else "COMPLETED"
        
        detail.comment = new_comment
        detail.is_uncompleted = False
        detail.save(update_fields=['comment', 'is_uncompleted'])
    
    # Setelah update status, recalculate output
    recalculate_all_stages_output(joint_number, pin_or_box, bjo)
    
def reset_to_uncompleted_on_delete(joint_number, pin_or_box, bjo):
    """
    RESET SEMUA stages menjadi UNCOMPLETED ketika ada penghapusan COMPLETED detail
    Ini memastikan workflow kembali ke state yang konsisten
    """
    # Cek apakah masih ada detail tersisa
    remaining_details = WeldDetail.objects.filter(
        bjo=bjo,
        joint_number=joint_number,
        pin_or_box=pin_or_box
    ).order_by('created_at')
    
    total_count = remaining_details.count()
    
    if total_count == 0:
        # Tidak ada yang tersisa, tidak perlu reset
        return
    
    # ✅ RESET SEMUA DETAIL MENJADI UNCOMPLETED
    for detail in remaining_details:
        old_comment = detail.comment or ''
        
        # Update comment: COMPLETED → UNCOMPLETED
        if old_comment.startswith('COMPLETED'):
            new_comment = old_comment.replace('COMPLETED', 'UNCOMPLETED', 1)
        elif 'COMPLETED' in old_comment:
            new_comment = old_comment.replace('COMPLETED', 'UNCOMPLETED')
        else:
            new_comment = f"UNCOMPLETED | {old_comment}" if old_comment else "UNCOMPLETED"
        
        detail.comment = new_comment
        detail.is_uncompleted = True
        detail.save(update_fields=['comment', 'is_uncompleted'])
    
    # Recalculate output setelah reset
    recalculate_all_stages_output(joint_number, pin_or_box, bjo)


def calculate_weld_output_dynamic(is_uncompleted, joint_number, pin_or_box, bjo, exclude_detail_id=None):
    """
    AUTO-CALCULATE output berdasarkan history uncompleted stages
    
    LOGIC:
    1. Hitung berapa kali uncompleted sudah tercatat untuk joint ini
    2. Jika uncompleted: output = 1.0 / (uncompleted_count + 2)
    3. Jika completed: output = 1.0 - total_output_sebelumnya
    
    Examples:
    - Stage 1 (uncompleted): count=0 → 1.0/(0+2) = 0.5
    - Stage 2 (uncompleted): count=1 → 1.0/(1+2) = 0.333
    - Stage 3 (completed): output = 1.0 - (0.333+0.333) = 0.334
    
    Returns:
        Decimal: Output value untuk stage ini
    """
    from production.models import WeldDetail
    
    # Hitung berapa kali uncompleted sudah ada untuk joint ini
    query = WeldDetail.objects.filter(
        bjo=bjo,
        joint_number=joint_number,
        pin_or_box=pin_or_box,
        is_uncompleted=True
    )
    
    if exclude_detail_id:
        query = query.exclude(id=exclude_detail_id)
    
    uncompleted_count = query.count()
    
    if is_uncompleted:
        # ===== INTERMEDIATE STAGE (UNCOMPLETED) =====
        # +1 untuk stage ini, +1 untuk final completed
        total_stages = uncompleted_count + 2
        output_per_stage = Decimal('1.0') / total_stages
        return output_per_stage.quantize(Decimal('0.001'))
    else:
        # ===== FINAL STAGE (COMPLETED) =====
        # Hitung total output yang sudah tercatat
        total_output_so_far = WeldDetail.objects.filter(
            bjo=bjo,
            joint_number=joint_number,
            pin_or_box=pin_or_box
        )
        
        if exclude_detail_id:
            total_output_so_far = total_output_so_far.exclude(id=exclude_detail_id)
        
        total_output = total_output_so_far.aggregate(total=Sum('output'))['total'] or Decimal(0)
        
        # Output untuk completed = sisa yang dibutuhkan untuk mencapai 1.0
        remaining_output = Decimal('1.0') - total_output
        
        # Safety check: jangan sampai negatif
        if remaining_output <= 0:
            remaining_output = Decimal('1.0') / (uncompleted_count + 1)
        
        return remaining_output.quantize(Decimal('0.001'))


def recalculate_all_stages_output(joint_number, pin_or_box, bjo):
    """
    RE-CALCULATE semua output untuk joint ini agar total = 1.0
    Dipanggil setiap kali ada perubahan (tambah uncompleted baru, delete, etc)
    
    LOGIC:
    1. Ambil semua detail untuk joint ini (urut berdasarkan created_at)
    2. Hitung total stages = jumlah records
    3. Bagi rata: output_per_stage = 1.0 / total_stages
    4. Update semua records, record terakhir dapat sisa pembulatan
    """
    from production.models import WeldDetail
    
    details = WeldDetail.objects.filter(
        bjo=bjo,
        joint_number=joint_number,
        pin_or_box=pin_or_box
    ).order_by('created_at')
    
    total_stages = details.count()
    
    if total_stages == 0:
        return
    
    # Hitung output per stage
    output_per_stage = Decimal('1.0') / total_stages
    output_per_stage = output_per_stage.quantize(Decimal('0.001'))
    
    # Update semua detail
    total_assigned = Decimal('0')
    for i, detail in enumerate(details):
        if i == total_stages - 1:  # Last stage
            # Berikan sisa output agar total = 1.0
            detail.output = Decimal('1.0') - total_assigned
        else:  # Intermediate stages
            detail.output = output_per_stage
            total_assigned += output_per_stage
        
        detail.save(update_fields=['output'])


def get_finished_value_for_jobdetail(is_uncompleted, joint_number, pin_or_box, bjo, exclude_detail_id=None):
    """
    Hitung finished value untuk jobDetail berdasarkan output yang dihitung
    
    Returns:
        Decimal: Finished value untuk jobDetail
    """
    output = calculate_weld_output_dynamic(is_uncompleted, joint_number, pin_or_box, bjo, exclude_detail_id)
    
    # Finished value = output / 2 (karena 1 joint = 2 ends welding)
    finished = output / 2
    return finished.quantize(Decimal('0.001'))


def calculate_weld_output(is_uncompleted):
    """
    DEPRECATED - Gunakan calculate_weld_output_dynamic() untuk multi-stage support
    Function ini dipertahankan untuk backward compatibility
    """
    return 0.5 if is_uncompleted else 1.0

@require_GET
def check_connector_duplicate_ajax(request):
    """
    AJAX endpoint untuk validasi connector number dengan logic yang sama seperti backend
    ✅ Menggunakan Connector table, bukan WeldDetail
    """
    conn_number_raw = request.GET.get('conn_number', '')
    bjo_id = request.GET.get('bjo_id', None)
    joint_number = request.GET.get('joint_number', None)
    exclude_detail_id = request.GET.get('exclude_detail_id', None)
    
    # Clean connector number
    conn_number = clean_conn_number(conn_number_raw)
    
    if not conn_number:
        return JsonResponse({'is_duplicate': False, 'reason': 'empty'})
    
    try:
        # ✅ VALIDASI MENGGUNAKAN CONNECTOR TABLE
        existing_conn = Connector.objects.filter(conn_number=conn_number).first()
        
        if not existing_conn:
            # ✅ CASE 1: Connector number belum pernah digunakan sama sekali
            return JsonResponse({
                'is_duplicate': False,
                'reason': 'new',
                'message': 'Conn No baru (available)'
            })
        
        # ✅ CASE 2: Connector sudah ada, cek apakah untuk BJO + Joint yang sama
        if bjo_id and joint_number:
            try:
                bjo = JobHeader.objects.get(id=bjo_id)
                
                # Cek apakah connector ini untuk BJO + Joint yang sama
                if existing_conn.bjo.id == bjo.id and existing_conn.joint_number == joint_number:
                    # ✅ ALLOW: Sama persis BJO dan Joint Number-nya
                    return JsonResponse({
                        'is_duplicate': False,
                        'reason': 'same_bjo_joint',
                        'message': 'Conn No sama untuk BJO dan Joint yang sama (OK)'
                    })
                else:
                    # ❌ BLOCK: Connector sudah dipakai oleh BJO+Joint yang berbeda
                    return JsonResponse({
                        'is_duplicate': True,
                        'bjo_number': existing_conn.bjo.bjo,
                        'joint_number': existing_conn.joint_number,
                        'reason': 'different_bjo_joint',
                        'message': f"Conn No sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' Joint '{existing_conn.joint_number}'"
                    })
                    
            except JobHeader.DoesNotExist:
                # BJO tidak valid
                return JsonResponse({
                    'is_duplicate': True,
                    'bjo_number': existing_conn.bjo.bjo,
                    'joint_number': existing_conn.joint_number,
                    'reason': 'invalid_bjo'
                })
        else:
            # ❌ BLOCK: BJO atau Joint Number tidak lengkap, anggap duplicate
            return JsonResponse({
                'is_duplicate': True,
                'bjo_number': existing_conn.bjo.bjo,
                'joint_number': existing_conn.joint_number,
                'reason': 'incomplete_data',
                'message': 'Pilih BJO dan Joint Number dulu untuk validasi yang akurat'
            })
    
    except Exception as e:
        # Log error untuk debugging
        import traceback
        print(f"Error in check_connector_duplicate_ajax: {str(e)}")
        print(traceback.format_exc())
        
        return JsonResponse({
            'is_duplicate': False,
            'error': str(e),
            'reason': 'error'
        }, status=500)

@welding_access_required
def weld_detail(request, header_id):
    header = get_object_or_404(WeldHeader, pk=header_id)

    if request.method == 'POST':
        # ===== CEK AKSES UNTUK POSTED RECORDS =====
        if header.is_posted:
            if request.user.role not in ['admin', 'supervisor']:
                messages.error(
                    request, 
                    "Access Denied: Only Admin and Supervisor can modify posted records."
                )
                return redirect('weld_detail', header_id=header.id)
            else:
                header.is_posted = False
                header.save(update_fields=['is_posted'])
                messages.warning(
                    request,
                    "Status record telah dikembalikan ke DRAFT karena ada perubahan data."
                )
        
        action = request.POST.get('action')
        
        if action == 'update_consumable':
            return handle_update_weld_consumable(request, header)
        
        if action == 'edit_time':
            return handle_edit_time_weld_detail(request, header_id)
        
        if action == 'edit':
            return handle_edit_weld_detail(request, header_id)

        try:
            with transaction.atomic():
                start_time_str = request.POST.get('start_time')
                stop_time_str = request.POST.get('stop_time')

                if not start_time_str or not stop_time_str:
                    messages.error(request, "Start Time dan Stop Time wajib diisi.")
                    return redirect('weld_detail', header_id=header.id)

                try:
                    start_time = datetime.strptime(start_time_str, '%H:%M').time()
                    stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
                except ValueError:
                    messages.error(request, "Format waktu tidak valid.")
                    return redirect('weld_detail', header_id=header.id)

                start_minutes = start_time.hour * 60 + start_time.minute
                stop_minutes = stop_time.hour * 60 + stop_time.minute

                if start_time == stop_time:
                    messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
                    return redirect('weld_detail', header_id=header.id)

                if stop_minutes < start_minutes:
                    duration = (stop_minutes + 24 * 60) - start_minutes
                else:
                    duration = stop_minutes - start_minutes

                if duration > 24 * 60:
                    messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
                    return redirect('weld_detail', header_id=header.id)

                bjo_id = request.POST.get('bjo')
                if not bjo_id:
                    messages.error(request, "BJO wajib dipilih.")
                    return redirect('weld_detail', header_id=header.id)

                try:
                    bjo = JobHeader.objects.get(id=bjo_id)
                except JobHeader.DoesNotExist:
                    messages.error(request, "BJO yang dipilih tidak valid.")
                    return redirect('weld_detail', header_id=header.id)

                pin_or_box_raw = request.POST.get('pin_or_box', '').strip()
                
                import re
                pin_or_box = re.sub(r'\s*\(.*?\)\s*', '', pin_or_box_raw).strip()
                
                if pin_or_box_raw != pin_or_box:
                    print(f"Cleaned pin_or_box: '{pin_or_box_raw}' -> '{pin_or_box}'")
                
                is_rework_from_selection = '(REWORK)' in pin_or_box_raw
                
                valid_options = ['PIN', 'BOX', 'FLOAT SHOE', 'FLOAT COLAR PIN SIDE', 'FLOAT COLAR BOX SIDE']
                if pin_or_box not in valid_options:
                    messages.error(
                        request, 
                        f"Pin/Box/Float tidak valid (diterima: '{pin_or_box}'). "
                        f"Harus salah satu dari: {', '.join(valid_options)}."
                    )
                    return redirect('weld_detail', header_id=header.id)

                job_operation = request.POST.get('job_operation', '').strip()
                if not job_operation:
                    messages.error(request, "Job Operation wajib diisi.")
                    return redirect('weld_detail', header_id=header.id)
                
                if len(job_operation) > 3:
                    messages.error(request, "Job Operation maksimal 3 karakter.")
                    return redirect('weld_detail', header_id=header.id)

                ct = None
                ct_str = request.POST.get('ct')
                if ct_str:
                    try:
                        ct = float(ct_str)
                        if ct < 0:
                            messages.error(request, "CT tidak boleh negatif.")
                            return redirect('weld_detail', header_id=header.id)
                    except ValueError:
                        messages.error(request, "CT harus berupa angka.")
                        return redirect('weld_detail', header_id=header.id)

                joint_number = request.POST.get('joint_number', '').strip()
                if not joint_number:
                    messages.error(request, "Connection Number wajib dipilih.")
                    return redirect('weld_detail', header_id=header.id)

                existing_completed = WeldDetail.objects.filter(
                    bjo=bjo,
                    joint_number=joint_number, 
                    pin_or_box=pin_or_box,
                    is_uncompleted=False
                ).first()
                
                is_rework = False
                is_merge_rework = False
                rework_detail = None
                
                if existing_completed:
                    has_ncr = WeldNcr.objects.filter(serial=existing_completed).exists()
                    
                    if has_ncr:
                        if has_been_reworked(existing_completed):
                            messages.error(
                                request, 
                                f"Joint '{joint_number}' - sisi {pin_or_box} sudah pernah di-REWORK untuk BJO '{bjo.bjo}'. "
                                "Tidak dapat di-rework lagi (maksimal 1x rework)."
                            )
                            return redirect('weld_detail', header_id=header.id)
                        
                        if existing_completed.Reff.id == header.id:
                            is_rework = True
                            is_merge_rework = True
                            rework_detail = existing_completed
                        else:
                            is_rework = True
                            is_merge_rework = False
                    else:
                        messages.error(
                            request, 
                            f"Joint '{joint_number}' - sisi {pin_or_box} sudah COMPLETED untuk BJO '{bjo.bjo}' dan bukan NCR."
                        )
                        return redirect('weld_detail', header_id=header.id)

                conn_number_raw = request.POST.get('conn_number', '')
                
                if not conn_number_raw or conn_number_raw.strip() == '':
                    messages.error(request, "Connection Number (Manual) wajib diisi.")
                    return redirect('weld_detail', header_id=header.id)

                conn_number = clean_conn_number(conn_number_raw)

                if not conn_number:
                    messages.error(request, "Connection Number tidak valid setelah dibersihkan.")
                    return redirect('weld_detail', header_id=header.id)

                if len(conn_number) > 20:
                    messages.error(request, "Connection Number maksimal 20 karakter (tanpa spasi).")
                    return redirect('weld_detail', header_id=header.id)
                
                # ✅ VALIDASI: conn_number harus GLOBALLY UNIQUE
                if not is_merge_rework:
                    existing_conn = Connector.objects.filter(conn_number=conn_number).first()

                    if existing_conn:
                        if existing_conn.bjo.id != bjo.id or existing_conn.joint_number != joint_number:
                            messages.error(
                                request,
                                f"Connection Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                                f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
                            )
                            return redirect('weld_detail', header_id=header.id)

                is_uncompleted = request.POST.get('is_uncompleted') == 'on'
                comment = request.POST.get('comment', '').strip()

                def detect_bjo_type(bjo):
                    bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
                    product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
                    process_name = bjo.process_type.name.upper() if bjo.process_type else ''
                    
                    if bjo_for:
                        if 'BOX' in bjo_for:
                            return 'box'
                        elif 'PIN' in bjo_for:
                            return 'pin'
                        elif 'PIPE' in bjo_for or 'WELDING' in bjo_for:
                            return 'pipe'
                    
                    if product and not bjo_for:
                        if 'BOX' in product:
                            return 'box'
                        elif 'PIN' in product:
                            return 'pin'
                    
                    if process_name and not bjo_for and not product:
                        if 'BOX' in process_name:
                            return 'box'
                        elif 'PIN' in process_name:
                            return 'pin'
                    
                    return 'pipe'

                bjo_type = detect_bjo_type(bjo)
                
                total_finished = jobDetail.objects.filter(job=bjo).aggregate(
                    total=Sum('finished')
                )['total'] or Decimal(0)
                remaining_qty = float(bjo.qty) - float(total_finished)
                
                required_finished = get_finished_value_for_jobdetail(
                    is_uncompleted=is_uncompleted,
                    joint_number=joint_number,
                    pin_or_box=pin_or_box,
                    bjo=bjo
                )
                required_qty = float(required_finished)

                if remaining_qty < required_qty:
                    messages.error(
                        request, 
                        f"Remaining quantity BJO {bjo.bjo} tidak mencukupi ({remaining_qty}). "
                        f"Minimal dibutuhkan {required_qty}."
                    )
                    return redirect('weld_detail', header_id=header.id)

                uncompleted_detail = None
                uncompleted_same_header = False
                is_completing_uncompleted = False

                existing_uncompleted = WeldDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo,
                    pin_or_box=pin_or_box,
                    is_uncompleted=True
                ).first()

                if existing_uncompleted and not is_uncompleted:
                    is_completing_uncompleted = True
                    uncompleted_detail = existing_uncompleted
                    uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)

                # ========== PROCESS COMPLETION ==========
                if is_completing_uncompleted and uncompleted_detail:
                    old_comment = uncompleted_detail.comment or ''
                    
                    if uncompleted_same_header:
                        if comment:
                            merged_comment = f"COMPLETED | {comment}"
                            if old_comment and not old_comment.startswith('UNCOMPLETED'):
                                merged_comment = f"{old_comment} | COMPLETED | {comment}"
                        else:
                            merged_comment = "COMPLETED"
                            if old_comment:
                                merged_comment = f"{old_comment} | COMPLETED"
                        
                        calculated_output = calculate_weld_output_dynamic(
                            is_uncompleted=False,
                            joint_number=joint_number,
                            pin_or_box=pin_or_box,
                            bjo=bjo,
                            exclude_detail_id=uncompleted_detail.id
                        )
                        
                        uncompleted_detail.start_time = start_time
                        uncompleted_detail.stop_time = stop_time
                        uncompleted_detail.job_operation = job_operation
                        uncompleted_detail.ct = ct
                        uncompleted_detail.comment = merged_comment
                        uncompleted_detail.is_uncompleted = False
                        uncompleted_detail.pin_or_box = pin_or_box
                        uncompleted_detail.conn_number = conn_number
                        uncompleted_detail.output = calculated_output
                        uncompleted_detail.save()
                        
                        update_all_stages_status_on_completion(joint_number, pin_or_box, bjo)
                        recalculate_all_stages_output(joint_number, pin_or_box, bjo)
                        
                        try:
                            old_finished = get_finished_value_for_jobdetail(
                                is_uncompleted=True,
                                joint_number=joint_number,
                                pin_or_box=pin_or_box,
                                bjo=bjo
                            )
                            
                            jobDetail.objects.filter(
                                job=bjo,
                                remarks__icontains=f"{pin_or_box} welding for {joint_number}",
                                finished=old_finished
                            ).delete()
                            
                            new_finished = get_finished_value_for_jobdetail(
                                is_uncompleted=False,
                                joint_number=joint_number,
                                pin_or_box=pin_or_box,
                                bjo=bjo
                            )
                            
                            jobDetail.objects.create(
                                job=bjo,
                                box=None,
                                pin=None,
                                fs=None,
                                fc=None,
                                finished=new_finished,
                                remarks=f"Auto: {pin_or_box} welding for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                            )
                        except Exception as job_error:
                            print(f"Warning: Gagal update jobDetail: {str(job_error)}")
                        
                        # ✅ CREATE CONNECTOR - Langsung create, tidak cek existing
                        Connector.objects.create(
                            bjo=bjo,
                            joint_number=joint_number,
                            conn_number=conn_number
                        )
                        
                        messages.success(
                            request, 
                            f"Welding UNCOMPLETED berhasil di-COMPLETE untuk '{conn_number}'. "
                            f"Output: {calculated_output}. Semua stages telah diupdate menjadi COMPLETED."
                        )
                        return redirect('weld_detail', header_id=header.id)
                    
                    else:
                        # COMPLETION DI HEADER BERBEDA
                        old_uncompleted_comment = uncompleted_detail.comment or ''
                        
                        if comment:
                            merged_uncompleted_comment = f"COMPLETED | {comment}"
                            if old_uncompleted_comment and 'COMPLETED' not in old_uncompleted_comment:
                                merged_uncompleted_comment = f"{old_uncompleted_comment} | COMPLETED | {comment}"
                        else:
                            merged_uncompleted_comment = "COMPLETED"
                            if old_uncompleted_comment and 'COMPLETED' not in old_uncompleted_comment:
                                merged_uncompleted_comment = f"{old_uncompleted_comment} | COMPLETED"
                        
                        if len(merged_uncompleted_comment) > 50:
                            merged_uncompleted_comment = merged_uncompleted_comment[:47] + "..."
                        
                        old_calculated_output = calculate_weld_output_dynamic(
                            is_uncompleted=False,
                            joint_number=joint_number,
                            pin_or_box=pin_or_box,
                            bjo=bjo,
                            exclude_detail_id=uncompleted_detail.id
                        )
                        
                        uncompleted_detail.comment = merged_uncompleted_comment
                        uncompleted_detail.is_uncompleted = False
                        uncompleted_detail.pin_or_box = pin_or_box
                        uncompleted_detail.output = old_calculated_output
                        uncompleted_detail.save()
                        
                        new_calculated_output = calculate_weld_output_dynamic(
                            is_uncompleted=False,
                            joint_number=joint_number,
                            pin_or_box=pin_or_box,
                            bjo=bjo
                        )
                        
                        if comment:
                            new_comment = f"COMPLETED | {comment}"
                        else:
                            new_comment = "COMPLETED"
                        
                        if len(new_comment) > 50:
                            new_comment = new_comment[:47] + "..."
                        
                        weld_detail = WeldDetail.objects.create(
                            Reff=header,
                            start_time=start_time,
                            stop_time=stop_time,
                            bjo=bjo,
                            job_operation=job_operation,
                            pin_or_box=pin_or_box,
                            ct=ct,
                            joint_number=joint_number,
                            conn_number=conn_number,
                            is_uncompleted=False,
                            output=new_calculated_output,
                            comment=new_comment,
                        )
                        
                        update_all_stages_status_on_completion(joint_number, pin_or_box, bjo)
                        recalculate_all_stages_output(joint_number, pin_or_box, bjo)
                        
                        try:
                            finished_value = get_finished_value_for_jobdetail(
                                is_uncompleted=False,
                                joint_number=joint_number,
                                pin_or_box=pin_or_box,
                                bjo=bjo
                            )
                            
                            auto_remarks = f"Auto: {pin_or_box} welding COMPLETION for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} (from Header #{uncompleted_detail.Reff.id})"
                            if comment:
                                auto_remarks += f" | {comment}"
                            
                            if len(auto_remarks) > 100:
                                auto_remarks = auto_remarks[:97] + "..."
                            
                            jobDetail.objects.create(
                                job=bjo,
                                box=None,
                                pin=None,
                                fs=None,
                                fc=None,
                                finished=finished_value,
                                remarks=auto_remarks,
                            )
                        except Exception as job_error:
                            print(f"Warning: Gagal create jobDetail: {str(job_error)}")
                        
                        update_joint_welding_status(joint_number, pin_or_box)
                        
                        # ✅ CREATE CONNECTOR - Langsung create
                        Connector.objects.create(
                            bjo=bjo,
                            joint_number=joint_number,
                            conn_number=conn_number
                        )
                        
                        messages.success(
                            request, 
                            f"Welding UNCOMPLETED berhasil di-COMPLETE untuk '{conn_number}' (header berbeda). "
                            f"Semua stages telah diupdate menjadi COMPLETED."
                        )
                        return redirect('weld_detail', header_id=header.id)

                # ========== PROCESS REWORK MERGE ==========
                if is_merge_rework and rework_detail:
                    old_comment = rework_detail.comment or ''
                    
                    if comment:
                        merged_comment = f"REWORKED | {comment}"
                        if old_comment and not old_comment.startswith('REWORKED'):
                            merged_comment = f"{old_comment} | REWORKED | {comment}"
                    else:
                        merged_comment = "REWORKED"
                        if old_comment and not old_comment.startswith('REWORKED'):
                            merged_comment = f"{old_comment} | REWORKED"
                    
                    calculated_output = calculate_weld_output_dynamic(
                        is_uncompleted=False,
                        joint_number=joint_number,
                        pin_or_box=pin_or_box,
                        bjo=bjo,
                        exclude_detail_id=rework_detail.id
                    )
                    
                    rework_detail.start_time = start_time
                    rework_detail.stop_time = stop_time
                    rework_detail.job_operation = job_operation
                    rework_detail.ct = ct
                    rework_detail.comment = merged_comment
                    rework_detail.conn_number = conn_number
                    rework_detail.output = calculated_output
                    rework_detail.save()
                    
                    update_all_stages_status_on_completion(joint_number, pin_or_box, bjo)
                    recalculate_all_stages_output(joint_number, pin_or_box, bjo)
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        reason__isnull=True
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        reason__exact=''
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        disposition__isnull=True
                    ).update(disposition="REWORK")
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        disposition__exact=''
                    ).update(disposition="REWORK")
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        action__isnull=True
                    ).update(action="Welding rework performed")
                    
                    WeldNcr.objects.filter(
                        serial=rework_detail,
                        action__exact=''
                    ).update(action="Welding rework completed")
                    
                    # ✅ CREATE CONNECTOR - Langsung create
                    Connector.objects.create(
                        bjo=bjo,
                        joint_number=joint_number,
                        conn_number=conn_number
                    )
                    
                    messages.success(
                        request, 
                        f"Welding detail REWORK berhasil di-merge dengan record existing untuk '{conn_number}'. "
                        f"Output: {calculated_output}. Semua stages telah diupdate menjadi COMPLETED. "
                        f"Joint ini tidak akan muncul lagi di dropdown (maksimal 1x rework)."
                    )
                    
                    return redirect('weld_detail', header_id=header.id)

                # ========== CREATE NEW DETAIL ==========
                calculated_output = calculate_weld_output_dynamic(
                    is_uncompleted=is_uncompleted,
                    joint_number=joint_number,
                    pin_or_box=pin_or_box,
                    bjo=bjo
                )
                
                if is_rework:
                    if comment:
                        comment = f"REWORKED | {comment}"
                    else:
                        comment = "REWORKED"
                elif is_uncompleted:
                    if comment:
                        comment = f"UNCOMPLETED | {comment}"
                    else:
                        comment = "UNCOMPLETED"
                
                weld_detail = WeldDetail.objects.create(
                    Reff=header,
                    start_time=start_time,
                    stop_time=stop_time,
                    bjo=bjo,
                    job_operation=job_operation,
                    pin_or_box=pin_or_box,
                    ct=ct,
                    joint_number=joint_number,
                    conn_number=conn_number,
                    is_uncompleted=is_uncompleted,
                    output=calculated_output,
                    comment=comment if comment else None,
                )

                if not is_uncompleted and not is_rework:
                    update_all_stages_status_on_completion(joint_number, pin_or_box, bjo)

                recalculate_all_stages_output(joint_number, pin_or_box, bjo)

                if not is_rework:
                    try:
                        finished_value = get_finished_value_for_jobdetail(
                            is_uncompleted=is_uncompleted,
                            joint_number=joint_number,
                            pin_or_box=pin_or_box,
                            bjo=bjo
                        )
                        
                        uncompleted_marker = " [UNCOMPLETED]" if is_uncompleted else ""
                        auto_remarks = f"Auto: {pin_or_box} welding for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}{uncompleted_marker}"
                        
                        if len(auto_remarks) > 100:
                            auto_remarks = auto_remarks[:97] + "..."
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_value,
                            remarks=auto_remarks,
                        )
                    except Exception as job_error:
                        print(f"Warning: Gagal create jobDetail: {str(job_error)}")

                update_joint_welding_status(joint_number, pin_or_box)

                # ✅ CREATE CONNECTOR - Langsung create, TIDAK cek existing
                Connector.objects.create(
                    bjo=bjo,
                    joint_number=joint_number,
                    conn_number=conn_number
                )

                new_comment = comment or ''
                if 'NCR' in new_comment.upper() and not is_rework:
                    try:
                        WeldNcr.objects.create(serial=weld_detail)
                        if is_uncompleted:
                            messages.warning(
                                request, 
                                f"Welding UNCOMPLETED ditambahkan (output {calculated_output}). NCR created."
                            )
                        else:
                            messages.warning(
                                request, 
                                f"Welding detail ditambahkan. Output: {calculated_output}. Semua stages telah diupdate. NCR created."
                            )
                    except Exception as ncr_error:
                        messages.warning(request, f"Detail ditambahkan, tapi NCR gagal: {str(ncr_error)}")
                elif is_rework and not is_merge_rework:
                    other_detail = WeldDetail.objects.filter(
                        joint_number=joint_number,
                        pin_or_box=pin_or_box,
                        bjo=bjo
                    ).exclude(Reff=header).first()
                    
                    if other_detail:
                        WeldNcr.objects.filter(
                            serial=other_detail,
                            reason__isnull=True
                        ).update(reason="REWORKED in different header - Issue resolved")
                        
                        WeldNcr.objects.filter(
                            serial=other_detail,
                            reason__exact=''
                        ).update(reason="REWORKED in different header - Issue resolved")
                    
                    messages.success(
                        request, 
                        f"Welding detail REWORK berhasil ditambahkan untuk '{conn_number}'. "
                        f"Output: {calculated_output}. Semua stages telah diupdate. "
                        f"Joint ini tidak akan muncul lagi di dropdown (maksimal 1x rework)."
                    )
                else:
                    if is_uncompleted:
                        messages.warning(
                            request, 
                            f"Welding UNCOMPLETED ditambahkan (output {calculated_output})."
                        )
                    else:
                        messages.success(
                            request, 
                            f"Welding detail berhasil. Output: {calculated_output}. Semua stages telah diupdate menjadi COMPLETED."
                        )

                return redirect('weld_detail', header_id=header.id)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('weld_detail', header_id=header.id)

    # ============ GET REQUEST ============
    detail_list = WeldDetail.objects.filter(Reff=header).order_by('id')
    for detail in detail_list:
        detail.duration_minutes = calculate_time_duration(detail.start_time, detail.stop_time)
        
        try:
            detail.ncr_count = WeldNcr.objects.filter(serial=detail).count()
            detail.has_ncr = detail.ncr_count > 0
            detail.has_incomplete_ncr = WeldNcr.objects.filter(
                serial=detail,
                reason__isnull=True
            ).exists() or WeldNcr.objects.filter(
                serial=detail,
                reason__exact=''
            ).exists()
        except:
            detail.ncr_count = 0
            detail.has_ncr = False
            detail.has_incomplete_ncr = False

    existing_consumable = WeldConsumsion.objects.filter(Reff=header).first()
    
    def is_pipe_bjo(bjo):
        bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
        product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        if bjo_for:
            if 'BOX' in bjo_for or 'PIN' in bjo_for:
                return False
            if 'PIPE' in bjo_for or 'WELDING' in bjo_for:
                return True
        
        if product:
            if 'BOX' in product or 'PIN' in product:
                return False
        
        if process_name:
            if 'BOX' in process_name or 'PIN' in process_name:
                return False
        
        return True
    
    job_list = []
    for job in JobHeader.objects.filter(is_finish__in=[False, None]).order_by('bjo'):
        if is_pipe_bjo(job):
            total_finished = jobDetail.objects.filter(job=job).aggregate(
                total=Sum('finished')
            )['total'] or Decimal(0)
            remaining_qty = float(job.qty) - float(total_finished)
            
            min_required = 0.1
            
            if remaining_qty >= min_required:
                job_list.append(job)
    
    detail_count = detail_list.count()

    context = {
        'header': header,
        'detail_list': detail_list,
        'job_list': job_list,
        'detail_count': detail_count,
        'existing_consumable': existing_consumable,
    }
    return render(request, 'weld/detail.html', context)

@welding_write_access_required
def handle_update_weld_consumable(request, header):
    """Handle update welding consumable data - dengan auto revert untuk posted records"""
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit consumable data on posted records.'
            )
            return redirect('weld_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan consumable."
            )
    
    try:
        wire = request.POST.get("wire", 0)
        flux = request.POST.get("flux", 0)
        granding = request.POST.get("granding", 0)
        cutting = request.POST.get("cutting", 0)
        consumable_others = request.POST.get("consumable_others", 0)

        existing_consumable = WeldConsumsion.objects.filter(Reff=header).first()

        consumable_data = {
            'wire': float(wire or 0),
            'flux': float(flux or 0),
            'granding': float(granding or 0),
            'cutting': float(cutting or 0),
            'others': float(consumable_others or 0),
        }

        if existing_consumable:
            for key, value in consumable_data.items():
                setattr(existing_consumable, key, value)
            existing_consumable.save()
            messages.success(request, "Data consumable berhasil diupdate.")
        else:
            consumable_data['Reff'] = header
            WeldConsumsion.objects.create(**consumable_data)
            messages.success(request, "Data consumable berhasil disimpan.")

        return redirect('weld_detail', header_id=header.id)

    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menyimpan data consumable: {str(e)}")
        return redirect('weld_detail', header_id=header.id)


def get_connection_numbers(request):
    """
    AJAX untuk mengambil connection numbers berdasarkan BJO 
    ✅ FIXED: Mengirimkan informasi used_options untuk setiap joint
    """
    bjo_id = request.GET.get('bjo_id')
    header_id = request.GET.get('header_id')
    
    if not bjo_id:
        return JsonResponse({'connection_numbers': []})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        
        def detect_bjo_type(bjo):
            bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
            product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
            process_name = bjo.process_type.name.upper() if bjo.process_type else ''
            
            if bjo_for:
                if 'BOX' in bjo_for:
                    return 'box'
                elif 'PIN' in bjo_for:
                    return 'pin'
                elif 'PIPE' in bjo_for or 'WELDING' in bjo_for:
                    return 'pipe'
            
            if product and not bjo_for:
                if 'BOX' in product:
                    return 'box'
                elif 'PIN' in product:
                    return 'pin'
            
            if process_name and not bjo_for and not product:
                if 'BOX' in process_name:
                    return 'box'
                elif 'PIN' in process_name:
                    return 'pin'
            
            return 'pipe'

        def has_been_reworked(detail):
            """Check if detail sudah pernah di-rework"""
            comment = detail.comment or ''
            return 'REWORKED' in comment.upper()

        bjo_type = detect_bjo_type(bjo)
        connection_list = []
        
        # ===== COLLECT UNCOMPLETED JOINTS =====
        uncompleted_joints = {}
        uncompleted_details = WeldDetail.objects.filter(
            bjo=bjo,
            is_uncompleted=True
        )
        
        for detail in uncompleted_details:
            has_completed = WeldDetail.objects.filter(
                joint_number=detail.joint_number,
                bjo=bjo,
                pin_or_box=detail.pin_or_box,
                is_uncompleted=False
            ).exists()
            
            if not has_completed:
                key = (detail.joint_number, detail.pin_or_box)
                uncompleted_joints[key] = True
        
        # ===== COLLECT NCR JOINTS =====
        ncr_joints = {}
        completed_details = WeldDetail.objects.filter(
            bjo=bjo,
            is_uncompleted=False
        )
        
        for detail in completed_details:
            has_ncr = WeldNcr.objects.filter(serial=detail).exists()
            
            if has_ncr and not has_been_reworked(detail):
                key = (detail.joint_number, detail.pin_or_box)
                ncr_joints[key] = True
        
        # ===== COLLECT REWORKED JOINTS =====
        reworked_joints = {}
        for detail in completed_details:
            if has_been_reworked(detail):
                key = (detail.joint_number, detail.pin_or_box)
                reworked_joints[key] = True
        
        # ===== COLLECT COMPLETED NON-NCR JOINTS =====
        completed_non_ncr_joints = {}
        for detail in completed_details:
            if detail.is_uncompleted:
                continue
            
            has_ncr = WeldNcr.objects.filter(serial=detail).exists()
            if has_ncr or has_been_reworked(detail):
                continue
            
            key = (detail.joint_number, detail.pin_or_box)
            completed_non_ncr_joints[key] = True
        
        # ===== PROCESS BERDASARKAN BJO TYPE =====
        def process_joint(joint_num, joint_type):
            """Helper function untuk memproses setiap joint"""
            all_options = ['PIN', 'BOX', 'FLOAT SHOE', 'FLOAT COLAR PIN SIDE', 'FLOAT COLAR BOX SIDE']
            
            available_options = []
            used_options = []  # ✅ NEW: Track opsi yang sudah digunakan
            
            for opt in all_options:
                key = (joint_num, opt)
                
                # ❌ SKIP: Sudah di-rework
                if key in reworked_joints:
                    used_options.append(opt + ' (Reworked)')
                    continue
                
                # ❌ SKIP: Sudah completed non-NCR
                if key in completed_non_ncr_joints:
                    used_options.append(opt + ' (Completed)')
                    continue
                
                # ✅ CHECK: Apakah opsi ini sudah digunakan?
                existing = WeldDetail.objects.filter(
                    bjo=bjo,
                    joint_number=joint_num,
                    pin_or_box=opt
                ).exists()
                
                # ✅ AVAILABLE: Uncompleted (bisa di-complete)
                if key in uncompleted_joints:
                    available_options.append(opt + ' (COMPLETE UNCOMPLETED)')
                # ✅ AVAILABLE: NCR belum rework (bisa di-rework)
                elif key in ncr_joints:
                    available_options.append(opt + ' (REWORK)')
                # ✅ AVAILABLE: Belum pernah digunakan sama sekali
                elif not existing:
                    available_options.append(opt)
            
            # Hanya return jika ada opsi available
            if available_options:
                return {
                    'joint_number': joint_num,
                    'type': joint_type,
                    'available_options': available_options,
                    'used_options': used_options  # ✅ NEW: Informasi opsi yang sudah terpakai
                }
            return None
        
        # Process berdasarkan tipe BJO
        if bjo_type == 'box':
            protectors = BoxProtector.objects.filter(bjo=bjo, is_used=False).order_by('serial_number')
            for protector in protectors:
                result = process_joint(protector.serial_number, 'box_protector')
                if result:
                    connection_list.append(result)
                    
        elif bjo_type == 'pin':
            protectors = PinProtector.objects.filter(bjo=bjo, is_used=False).order_by('serial_number')
            for protector in protectors:
                result = process_joint(protector.serial_number, 'pin_protector')
                if result:
                    connection_list.append(result)
        
        else:  # PIPE
            serials = SerialNumber.objects.filter(bjo=bjo).order_by('joint_number')
            for serial in serials:
                result = process_joint(serial.joint_number, 'pipe')
                if result:
                    connection_list.append(result)

        return JsonResponse({
            'connection_numbers': connection_list,
            'bjo_type': bjo_type
        })

    except JobHeader.DoesNotExist:
        return JsonResponse({'connection_numbers': []})
    except Exception as e:
        return JsonResponse({
            'connection_numbers': [],
            'error': str(e)
        })

@require_GET
def check_conn_number_duplicate(request):
    conn_number_raw = request.GET.get('conn_number', '')
    conn_number = clean_conn_number(conn_number_raw)
    exclude_detail_id = request.GET.get('exclude_detail_id', None)
    
    if not conn_number:
        return JsonResponse({'is_duplicate': False})
    
    def has_been_reworked(detail):
        """
        Check if detail sudah pernah di-rework
        Returns True if REWORKED keyword exists in comment
        """
        comment = detail.comment or ''
        return 'REWORKED' in comment.upper()
    
    # Query untuk cek duplicate - CEK SEMUA detail dengan conn_number ini
    query = WeldDetail.objects.filter(conn_number=conn_number)
    
    # Exclude detail yang sedang diedit (untuk mode edit)
    if exclude_detail_id:
        try:
            query = query.exclude(id=int(exclude_detail_id))
        except (ValueError, TypeError):
            pass
    
    # ✅ CEK SEMUA DETAIL DENGAN CONN_NUMBER INI
    all_details = list(query.all())
    
    if not all_details:
        # ===== AVAILABLE: Belum pernah digunakan =====
        return JsonResponse({
            'is_duplicate': False,
            'message': 'Available (new)'
        })
    
    # ===== CRITICAL CHECK: CEK APAKAH ADA YANG SUDAH DI-REWORK =====
    # ❌ BLOCK jika ada salah satu detail yang sudah REWORKED (prioritas tertinggi!)
    for detail in all_details:
        if has_been_reworked(detail):
            bjo_number = detail.bjo.bjo if detail.bjo else 'N/A'
            joint_number = detail.joint_number or 'N/A'
            
            return JsonResponse({
                'is_duplicate': True,
                'bjo_number': bjo_number,
                'joint_number': joint_number,
                'message': 'Conn No sudah pernah di-REWORK (maksimal 1x rework)',
                'reason': 'already_reworked'
            })
    
    # ===== PRIORITY 1: CEK APAKAH ADA YANG UNCOMPLETED =====
    for detail in all_details:
        if detail.is_uncompleted:
            return JsonResponse({
                'is_duplicate': False,
                'message': 'Available for completion (Uncompleted)'
            })
    
    # ===== PRIORITY 2: CEK APAKAH ADA NCR (BELUM DI-REWORK) =====
    for detail in all_details:
        has_ncr = WeldNcr.objects.filter(serial=detail).exists()
        if has_ncr:
            # ✅ ALLOW: NCR belum pernah di-rework, masih boleh untuk rework pertama kali
            return JsonResponse({
                'is_duplicate': False,
                'message': 'Available for rework (NCR - belum pernah rework)'
            })
    
    # ===== PRIORITY 3: COMPLETED DAN BUKAN NCR (BLOCK) =====
    # ❌ BLOCK: Semua detail sudah completed dan bukan NCR
    first_detail = all_details[0]
    bjo_number = first_detail.bjo.bjo if first_detail.bjo else 'N/A'
    joint_number = first_detail.joint_number or 'N/A'
    
    return JsonResponse({
        'is_duplicate': True,
        'bjo_number': bjo_number,
        'joint_number': joint_number,
        'message': 'Conn No sudah digunakan dan bukan NCR/Uncompleted',
        'reason': 'completed_non_ncr'
    })

def get_weld_ct_values(request):
    """AJAX untuk mengambil nilai CT berdasarkan BJO yang dipilih untuk welding"""
    bjo_id = request.GET.get('bjo_id')
    if not bjo_id:
        return JsonResponse({'ct': None})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        ct_value = None
        
        if bjo.size and bjo.ct_reference and bjo.process_type:
            try:
                cycle_time = CycleTime.objects.get(
                    process_type=bjo.process_type,
                    od_thickness=bjo.size,
                    ct_for=bjo.ct_reference
                )
                ct_value = float(cycle_time.hours) if cycle_time.hours else None
            except CycleTime.DoesNotExist:
                pass

        return JsonResponse({
            'ct': ct_value,
            'bjo_info': {
                'size': str(bjo.size) if bjo.size else None,
                'grade': str(bjo.ct_reference) if bjo.ct_reference else None,
                'process': str(bjo.process_type) if bjo.process_type else None
            }
        })

    except JobHeader.DoesNotExist:
        return JsonResponse({'ct': None})

@welding_detail_edit_access_required
def handle_edit_weld_detail(request, header_id):
    """Handle edit welding detail with multi-stage support and GLOBAL UNIQUE connector validation"""
    header = get_object_or_404(WeldHeader, pk=header_id)
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit details on posted records.'
            )
            return redirect('weld_detail', header_id=header.id)
        else:
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan detail."
            )
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    
    try:
        detail = WeldDetail.objects.get(id=detail_id, Reff=header)
        old_comment = detail.comment or ''
        old_is_uncompleted = detail.is_uncompleted
        old_joint_number = detail.joint_number
        old_pin_or_box = detail.pin_or_box
        old_conn_number = detail.conn_number or ''
        old_bjo = detail.bjo
    except WeldDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    
    try:
        start_time_str = request.POST.get('start_time')
        stop_time_str = request.POST.get('stop_time')
        
        if not start_time_str or not stop_time_str:
            messages.error(request, "Start Time dan Stop Time wajib diisi.")
            return redirect('weld_detail', header_id=header.id)
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format waktu tidak valid.")
            return redirect('weld_detail', header_id=header.id)
        
        start_minutes = start_time.hour * 60 + start_time.minute
        stop_minutes = stop_time.hour * 60 + stop_time.minute

        if start_time == stop_time:
            messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
            return redirect('weld_detail', header_id=header.id)

        if stop_minutes < start_minutes:
            duration = (stop_minutes + 24 * 60) - start_minutes
        else:
            duration = stop_minutes - start_minutes

        if duration > 24 * 60:
            messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
            return redirect('weld_detail', header_id=header.id)
        
        job_operation = request.POST.get('job_operation', '').strip()
        if not job_operation:
            messages.error(request, "Job Operation wajib diisi.")
            return redirect('weld_detail', header_id=header.id)
        
        if len(job_operation) > 3:
            messages.error(request, "Job Operation maksimal 3 karakter.")
            return redirect('weld_detail', header_id=header.id)

        pin_or_box = request.POST.get('pin_or_box')
        valid_options = ['PIN', 'BOX', 'FLOAT SHOE', 'FLOAT COLAR PIN SIDE', 'FLOAT COLAR BOX SIDE']
        if pin_or_box not in valid_options:
            messages.error(request, f"Pin/Box/Float harus salah satu dari: {', '.join(valid_options)}.")
            return redirect('weld_detail', header_id=header.id)
        
        ct = None
        ct_str = request.POST.get('ct')
        if ct_str:
            try:
                ct = float(ct_str)
                if ct < 0:
                    messages.error(request, "CT tidak boleh negatif.")
                    return redirect('weld_detail', header_id=header.id)
            except ValueError:
                messages.error(request, "CT harus berupa angka.")
                return redirect('weld_detail', header_id=header.id)
        
        new_joint_number = request.POST.get('joint_number', '').strip()
        if not new_joint_number:
            messages.error(request, "Joint Number wajib diisi.")
            return redirect('weld_detail', header_id=header.id)
        
        conn_number_raw = request.POST.get('conn_number', '')
        
        if not conn_number_raw or conn_number_raw.strip() == '':
            messages.error(request, "Connection Number (Manual) wajib diisi.")
            return redirect('weld_detail', header_id=header.id)

        conn_number = clean_conn_number(conn_number_raw)

        if not conn_number:
            messages.error(request, "Connection Number tidak valid setelah dibersihkan.")
            return redirect('weld_detail', header_id=header.id)

        if len(conn_number) > 20:
            messages.error(request, "Connection Number maksimal 20 karakter (tanpa spasi).")
            return redirect('weld_detail', header_id=header.id)
        
        key_changed = (
            new_joint_number != old_joint_number or 
            pin_or_box != old_pin_or_box
        )
        
        if key_changed:
            existing_combination = WeldDetail.objects.filter(
                bjo=old_bjo,
                joint_number=new_joint_number,
                pin_or_box=pin_or_box,
                is_uncompleted=False
            ).exclude(id=detail.id).first()
            
            if existing_combination:
                has_ncr = WeldNcr.objects.filter(serial=existing_combination).exists()
                if not has_ncr:
                    messages.error(request, f"Joint '{new_joint_number}' - sisi {pin_or_box} sudah pernah di-weld untuk BJO '{old_bjo.bjo}' dan bukan NCR.")
                    return redirect('weld_detail', header_id=header.id)
        
        conn_changed = conn_number != old_conn_number.upper()
        
        # ✅ VALIDASI CONNECTOR NUMBER - GLOBAL UNIQUE
        if conn_changed:
            existing_conn = Connector.objects.filter(conn_number=conn_number).first()

            if existing_conn:
                if existing_conn.bjo.id != old_bjo.id or existing_conn.joint_number != detail.joint_number:
                    messages.error(
                        request,
                        f"Connection Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                        f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
                    )
                    return redirect('weld_detail', header_id=header.id)
        
        toggle_status = request.POST.get('toggle_status')
        
        if toggle_status is not None:
            new_is_uncompleted = request.POST.get('is_uncompleted') == 'on'
        else:
            new_is_uncompleted = old_is_uncompleted
        
        comment = request.POST.get('comment', '').strip()
        
        # ===== HANDLE PERUBAHAN STATUS UNCOMPLETED =====
        if old_is_uncompleted != new_is_uncompleted:
            bjo = detail.bjo
            bjo.refresh_from_db()
            
            if new_is_uncompleted and not old_is_uncompleted:
                # ===== COMPLETE → UNCOMPLETED =====
                try:
                    old_finished = get_finished_value_for_jobdetail(
                        is_uncompleted=False,
                        joint_number=detail.joint_number,
                        pin_or_box=detail.pin_or_box,
                        bjo=bjo
                    )
                    
                    jobDetail.objects.filter(
                        job=bjo,
                        remarks__icontains=f"{detail.pin_or_box} welding for {detail.joint_number}",
                        finished=old_finished
                    ).delete()
                    
                    new_finished = get_finished_value_for_jobdetail(
                        is_uncompleted=True,
                        joint_number=detail.joint_number,
                        pin_or_box=detail.pin_or_box,
                        bjo=bjo
                    )
                    
                    jobDetail.objects.create(
                        job=bjo,
                        box=None,
                        pin=None,
                        fs=None,
                        fc=None,
                        finished=new_finished,
                        remarks=f"Auto: {detail.pin_or_box} welding for {detail.joint_number} [UNCOMPLETED]"
                    )
                except Exception as job_error:
                    print(f"Warning: Gagal update jobDetail: {str(job_error)}")
                
                old_comment_clean = old_comment.replace('COMPLETED |', '').replace('| COMPLETED', '').strip()
                if comment:
                    comment = f"UNCOMPLETED | {comment}"
                else:
                    if old_comment_clean:
                        comment = f"UNCOMPLETED | {old_comment_clean}"
                    else:
                        comment = "UNCOMPLETED"
                
                calculated_output = calculate_weld_output_dynamic(
                    is_uncompleted=True,
                    joint_number=detail.joint_number,
                    pin_or_box=detail.pin_or_box,
                    bjo=bjo,
                    exclude_detail_id=detail.id
                )
                
                detail.output = calculated_output
                
                messages.info(request, f"Status berubah menjadi UNCOMPLETED. Output: {calculated_output}.")
                
            elif not new_is_uncompleted and old_is_uncompleted:
                # ===== UNCOMPLETED → COMPLETE =====
                existing_uncompleted_same_header = WeldDetail.objects.filter(
                    Reff=header,
                    joint_number=detail.joint_number,
                    bjo=bjo,
                    pin_or_box=detail.pin_or_box,
                    is_uncompleted=True
                ).exclude(id=detail.id).first()
                
                if existing_uncompleted_same_header:
                    old_uncompleted_comment = existing_uncompleted_same_header.comment or ''
                    
                    if comment:
                        merged_comment = f"COMPLETED | {comment}"
                        if old_uncompleted_comment and not old_uncompleted_comment.startswith('COMPLETED'):
                            merged_comment = f"{old_uncompleted_comment} | COMPLETED | {comment}"
                    else:
                        merged_comment = "COMPLETED"
                        if old_uncompleted_comment:
                            merged_comment = f"{old_uncompleted_comment} | COMPLETED"
                    
                    calculated_output = calculate_weld_output_dynamic(
                        is_uncompleted=False,
                        joint_number=detail.joint_number,
                        pin_or_box=detail.pin_or_box,
                        bjo=bjo,
                        exclude_detail_id=existing_uncompleted_same_header.id
                    )
                    
                    existing_uncompleted_same_header.start_time = start_time
                    existing_uncompleted_same_header.stop_time = stop_time
                    existing_uncompleted_same_header.job_operation = job_operation
                    existing_uncompleted_same_header.ct = ct
                    existing_uncompleted_same_header.comment = merged_comment
                    existing_uncompleted_same_header.is_uncompleted = False
                    existing_uncompleted_same_header.output = calculated_output
                    existing_uncompleted_same_header.conn_number = conn_number
                    existing_uncompleted_same_header.save()
                    
                    detail.delete()
                    
                    update_all_stages_status_on_completion(detail.joint_number, detail.pin_or_box, bjo)
                    recalculate_all_stages_output(detail.joint_number, detail.pin_or_box, bjo)
                    
                    try:
                        jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=f"{detail.pin_or_box} welding for {detail.joint_number}"
                        ).delete()
                        
                        new_finished = get_finished_value_for_jobdetail(
                            is_uncompleted=False,
                            joint_number=detail.joint_number,
                            pin_or_box=detail.pin_or_box,
                            bjo=bjo
                        )
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=new_finished,
                            remarks=f"Auto: {detail.pin_or_box} welding for {detail.joint_number} [COMPLETED]"
                        )
                    except Exception as job_error:
                        print(f"Warning: Gagal update jobDetail: {str(job_error)}")
                    
                    # ✅ UPDATE CONNECTOR - Cari berdasarkan old_conn_number
                    if conn_changed:
                        old_connector = Connector.objects.filter(
                            bjo=bjo,
                            joint_number=detail.joint_number,
                            conn_number=old_conn_number
                        ).first()
                        
                        if old_connector:
                            old_connector.conn_number = conn_number
                            old_connector.save()
                    
                    messages.success(
                        request,
                        f"Welding UNCOMPLETED berhasil di-COMPLETE dan di-merge. "
                        f"Output: {calculated_output}. Semua stages telah diupdate menjadi COMPLETED."
                    )
                    
                    return redirect('weld_detail', header_id=header.id)
                    
                else:
                    try:
                        old_finished = get_finished_value_for_jobdetail(
                            is_uncompleted=True,
                            joint_number=detail.joint_number,
                            pin_or_box=detail.pin_or_box,
                            bjo=bjo
                        )
                        
                        jobDetail.objects.filter(
                            job=bjo,
                            remarks__icontains=f"{detail.pin_or_box} welding for {detail.joint_number}",
                            finished=old_finished
                        ).delete()
                        
                        new_finished = get_finished_value_for_jobdetail(
                            is_uncompleted=False,
                            joint_number=detail.joint_number,
                            pin_or_box=detail.pin_or_box,
                            bjo=bjo
                        )
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=new_finished,
                            remarks=f"Auto: {detail.pin_or_box} welding for {detail.joint_number} [COMPLETED]"
                        )
                    except Exception as job_error:
                        print(f"Warning: Gagal update jobDetail: {str(job_error)}")
                    
                    old_comment_clean = old_comment.replace('UNCOMPLETED |', '').replace('| UNCOMPLETED', '').strip()
                    if comment:
                        comment = f"COMPLETED | {comment}"
                    else:
                        if old_comment_clean:
                            comment = f"COMPLETED | {old_comment_clean}"
                        else:
                            comment = "COMPLETED"
                    
                    calculated_output = calculate_weld_output_dynamic(
                        is_uncompleted=False,
                        joint_number=detail.joint_number,
                        pin_or_box=detail.pin_or_box,
                        bjo=bjo,
                        exclude_detail_id=detail.id
                    )
                    
                    detail.output = calculated_output
                    update_all_stages_status_on_completion(detail.joint_number, detail.pin_or_box, bjo)
                    
                    messages.info(request, f"Status berubah menjadi COMPLETE. Output: {calculated_output}. Semua stages telah diupdate menjadi COMPLETED.")
        
        calculated_output = calculate_weld_output_dynamic(
            is_uncompleted=new_is_uncompleted,
            joint_number=new_joint_number,
            pin_or_box=pin_or_box,
            bjo=old_bjo,
            exclude_detail_id=detail.id
        )
        
        try:
            detail.refresh_from_db()
            detail.start_time = start_time
            detail.stop_time = stop_time
            detail.job_operation = job_operation
            detail.pin_or_box = pin_or_box
            detail.ct = ct
            detail.joint_number = new_joint_number
            detail.conn_number = conn_number
            detail.is_uncompleted = new_is_uncompleted
            detail.output = calculated_output
            detail.comment = comment if comment else None
            detail.save()
        except WeldDetail.DoesNotExist:
            pass
        
        recalculate_all_stages_output(new_joint_number, pin_or_box, old_bjo)
        
        # ✅ UPDATE CONNECTOR - Cari berdasarkan old_conn_number, update ke new
        if conn_changed:
            old_connector = Connector.objects.filter(
                bjo=old_bjo,
                joint_number=detail.joint_number,
                conn_number=old_conn_number
            ).first()
            
            if old_connector:
                old_connector.conn_number = conn_number
                old_connector.save()
        
        new_comment = comment or ''
        has_ncr_in_new = 'NCR' in new_comment.upper()
        has_ncr_in_old = 'NCR' in old_comment.upper()
        
        if has_ncr_in_new and not has_ncr_in_old:
            try:
                existing_ncr = WeldNcr.objects.filter(serial=detail).exists()
                
                if not existing_ncr:
                    WeldNcr.objects.create(serial=detail)
                    messages.warning(
                        request, 
                        f"Welding detail berhasil diupdate. Output: {calculated_output}. "
                        f"NCR record telah dibuat untuk connection '{conn_number}'."
                    )
                else:
                    messages.success(request, f"Welding detail berhasil diupdate. Output: {calculated_output}.")
                    
            except Exception as ncr_error:
                messages.warning(
                    request,
                    f"Welding detail berhasil diupdate dengan output: {calculated_output}, "
                    f"namun gagal membuat NCR record: {str(ncr_error)}"
                )
                
        else:
            if old_is_uncompleted == new_is_uncompleted:
                messages.success(request, f"Welding detail berhasil diupdate. Output: {calculated_output}.")
        
        return redirect('weld_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('weld_detail', header_id=header.id)

@welding_management_access_required
def weld_detail_delete(request, header_id):
    """Delete welding detail dengan auto revert posted status, multi-stage recalculation, dan delete connector"""
    header = get_object_or_404(WeldHeader, pk=header_id)
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                "Access Denied: Only Admin and Supervisor can delete details on posted records."
            )
            return redirect('weld_detail', header_id=header.id)
        else:
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada penghapusan detail."
            )
    
    if request.method != 'POST':
        messages.error(request, "Method tidak diizinkan.")
        return redirect('weld_detail', header_id=header.id)
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    
    try:
        with transaction.atomic():
            detail = WeldDetail.objects.get(id=detail_id, Reff=header)
            
            joint_number = detail.joint_number
            pin_or_box = detail.pin_or_box
            bjo = detail.bjo
            is_uncompleted = detail.is_uncompleted
            output_value = detail.output or 0
            conn_number = detail.conn_number
            
            deleted_finished_value = 0
            try:
                finished_val = get_finished_value_for_jobdetail(
                    is_uncompleted=is_uncompleted,
                    joint_number=joint_number,
                    pin_or_box=pin_or_box,
                    bjo=bjo
                )
                
                deleted_count = jobDetail.objects.filter(
                    job=bjo,
                    remarks__icontains=f"{pin_or_box} welding for {joint_number}",
                    finished=finished_val
                ).delete()[0]
                
                if deleted_count > 0:
                    deleted_finished_value = float(finished_val)
                
            except Exception as job_detail_error:
                print(f"Warning: Gagal menghapus jobDetail: {str(job_detail_error)}")
            
            # DELETE DETAIL
            detail.delete()
            
            # ✅ DELETE CONNECTOR - Berdasarkan CONN_NUMBER yang spesifik
            try:
                deleted_connector = Connector.objects.filter(
                    bjo=bjo,
                    joint_number=joint_number,
                    conn_number=conn_number
                ).delete()
                
                if deleted_connector[0] > 0:
                    print(f"INFO: Connector '{conn_number}' untuk BJO '{bjo.bjo}' Joint '{joint_number}' telah dihapus.")
            except Exception as conn_error:
                print(f"Warning: Gagal menghapus Connector: {str(conn_error)}")
            
            # ✅ RESET status jika perlu
            if not is_uncompleted:
                reset_to_uncompleted_on_delete(joint_number, pin_or_box, bjo)
            
            # ✅ RECALCULATE ALL REMAINING STAGES
            recalculate_all_stages_output(joint_number, pin_or_box, bjo)
            
            try:
                total_finished = jobDetail.objects.filter(job=bjo).aggregate(
                    total=Sum('finished')
                )['total'] or Decimal(0)
                
                bjo.refresh_from_db()
                remaining_qty = float(bjo.qty) - float(total_finished)
                
                if remaining_qty > 0:
                    bjo.is_finish = False
                    bjo.save(update_fields=['is_finish'])
                    
            except Exception as status_error:
                print(f"Warning: Gagal mengupdate status is_finish: {str(status_error)}")
            
            messages.success(
                request, 
                f"Detail welding untuk connection '{conn_number}' berhasil dihapus. "
                f"Output yang dihapus: {output_value}. Connector '{conn_number}' juga telah dihapus."
            )
                
            return redirect('weld_detail', header_id=header.id)
            
    except WeldDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus: {str(e)}")
        return redirect('weld_detail', header_id=header.id)

@welding_management_access_required
def handle_edit_time_weld_detail(request, header_id):
    """Handle edit welding detail time only with duration-based calculation"""
    header = get_object_or_404(WeldHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit time on posted records.'
            )
            return redirect('weld_detail', header_id=header.id)
        else:
            # ===== AUTO REVERT POSTED STATUS =====
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan waktu."
            )
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    
    try:
        detail = WeldDetail.objects.get(id=detail_id, Reff=header)
    except WeldDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('weld_detail', header_id=header.id)
    
    try:
        start_time_str = request.POST.get('start_time')
        if not start_time_str:
            messages.error(request, "Start Time wajib diisi.")
            return redirect('weld_detail', header_id=header.id)
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format waktu tidak valid.")
            return redirect('weld_detail', header_id=header.id)
        
        duration_str = request.POST.get('duration_hours')
        if not duration_str:
            messages.error(request, "Durasi (jam) wajib diisi.")
            return redirect('weld_detail', header_id=header.id)
        
        try:
            duration_hours = float(duration_str)
            if duration_hours <= 0:
                messages.error(request, "Durasi harus lebih dari 0.")
                return redirect('weld_detail', header_id=header.id)
            if duration_hours > 24:
                messages.error(request, "Durasi maksimal 24 jam per shift.")
                return redirect('weld_detail', header_id=header.id)
        except ValueError:
            messages.error(request, "Format durasi tidak valid.")
            return redirect('weld_detail', header_id=header.id)
        
        start_datetime = datetime.combine(datetime.today(), start_time)
        stop_datetime = start_datetime + timedelta(hours=duration_hours)
        stop_time = stop_datetime.time()
        
        detail.start_time = start_time
        detail.stop_time = stop_time
        detail.save()
        
        messages.success(request, f"Waktu welding berhasil diupdate. Start: {start_time.strftime('%H:%M')}, Stop: {stop_time.strftime('%H:%M')} (Durasi: {duration_hours} jam)")
        return redirect('weld_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('weld_detail', header_id=header.id)

@welding_management_access_required
def finalisasi_weld(request, pk):
    header = get_object_or_404(WeldHeader, pk=pk)

    def calculate_totals():
        detail_qs = WeldDetail.objects.filter(Reff=header)
        total_hours = 0

        for d in detail_qs:
            if d.start_time and d.stop_time:
                duration_hours = calculate_time_duration(d.start_time, d.stop_time)
                if duration_hours:
                    total_hours += duration_hours

        total_output = detail_qs.aggregate(Sum('output'))['output__sum'] or 0
        total_output = round(total_output, 2)
        actual_output = total_output
        actual_hours = round(total_hours, 2)

        return total_output, total_hours, actual_output, actual_hours

    # ===== PREPARE BJO DATA =====
    bjos_in_shift = WeldDetail.objects.filter(Reff=header).values_list('bjo', flat=True).distinct()
    bjos_list = JobHeader.objects.filter(id__in=bjos_in_shift)

    bjos_data = []
    for bjo in bjos_list:
        joint_numbers = WeldDetail.objects.filter(
            Reff=header,
            bjo=bjo,
            is_uncompleted=False
        ).values_list('joint_number', flat=True).distinct()

        reason_stop = WeldReasonStop.objects.filter(
            Reff=header,
            bjo=bjo
        ).first()

        # Load existing maintenance per BJO
        existing_bjo_maintenance = Maintenance.objects.filter(
            weld_machine=header,
            bjo=bjo
        ).first()

        bjos_data.append({
            'id': bjo.id,
            'bjo': bjo.bjo,
            'customer': bjo.customer,
            'size': bjo.size,
            'qty': bjo.qty,
            'joint_numbers': list(joint_numbers),
            'reject': reason_stop.reject if reason_stop else 0,
            'cutback': reason_stop.cutback if reason_stop else 0,
            'change_over': reason_stop.change_over if reason_stop else 0,
            'change_over_comment': reason_stop.change_over_comment if reason_stop else '',
            # Maintenance per BJO
            'maint_duration': existing_bjo_maintenance.duration if existing_bjo_maintenance else 0,
            'maint_cost': existing_bjo_maintenance.cost if existing_bjo_maintenance else 0,
            'maint_issue': existing_bjo_maintenance.issue if existing_bjo_maintenance else '',
        })

    existing_shared_reason_stop = WeldReasonStop.objects.filter(Reff=header, bjo=None).first()

    total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

    booked_duration = float(header.booked_hours.duration) if header.booked_hours else 0
    time_difference = 0
    need_reason_explanation = False
    is_overtime = False

    if request.method == "POST":
        # RECALCULATE totals
        total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

        actual_output = request.POST.get("actual_output")
        actual_hours = request.POST.get("actual_hours")
        comment = request.POST.get("comment", "").strip()

        if not actual_output:
            actual_output = str(auto_actual_output)
        if not actual_hours:
            actual_hours = str(auto_actual_hours)

        user_input_hours = float(actual_hours)

        if abs(user_input_hours - auto_actual_hours) <= 0.01:
            actual_hours = str(auto_actual_hours)
            actual_hours_float = auto_actual_hours
        elif request.POST.get('force_refresh') == 'true':
            actual_hours = str(auto_actual_hours)
            actual_hours_float = auto_actual_hours
        else:
            actual_hours_float = user_input_hours

        if total_qty == 0:
            messages.error(request, "Tidak bisa menyelesaikan finalisasi karena detail masih kosong.")
            return redirect("weld_detail", pk=header.pk)

        if not actual_output or not actual_hours:
            messages.error(request, "Actual Output dan Actual Hours wajib diisi.")
            return render(request, "weld/final.html", {
                "header": header,
                "total_qty": total_qty,
                "total_hours": round(total_hours, 2),
                "booked_duration": booked_duration,
                "time_difference": 0,
                "need_reason_explanation": False,
                "is_overtime": False,
                "bjos_data": bjos_data,
                "existing_shared_reason_stop": existing_shared_reason_stop,
                "auto_actual_output": auto_actual_output,
                "auto_actual_hours": auto_actual_hours,
            })

        time_difference = booked_duration - actual_hours_float

        overtime_tolerance = 0.5

        # Handle overtime tolerance (≤ 30 menit disesuaikan otomatis)
        if -overtime_tolerance <= time_difference < -0.0167:
            original_actual_hours = actual_hours_float
            actual_hours = str(booked_duration)
            actual_hours_float = booked_duration
            time_difference = 0
            messages.info(
                request,
                f"Kelebihan waktu {abs(booked_duration - original_actual_hours):.2f} jam "
                f"(≤ 30 menit) telah disesuaikan otomatis ke Booked Hours ({booked_duration:.2f} jam)."
            )

        elif time_difference < -overtime_tolerance:
            original_actual_hours = actual_hours_float
            overtime_amount = original_actual_hours - booked_duration
            messages.error(
                request,
                f"Kelebihan waktu {overtime_amount:.2f} jam melebihi toleransi 30 menit. "
                f"Actual Hours ({original_actual_hours:.2f} jam) hanya boleh maksimal "
                f"{booked_duration + overtime_tolerance:.2f} jam (Booked Hours + 30 menit). "
                f"Silakan sesuaikan waktu kerja atau hubungi supervisor."
            )
            return render(request, "weld/final.html", {
                "header": header,
                "total_qty": total_qty,
                "total_hours": round(total_hours, 2),
                "booked_duration": booked_duration,
                "time_difference": 0,
                "need_reason_explanation": False,
                "is_overtime": False,
                "bjos_data": bjos_data,
                "existing_shared_reason_stop": existing_shared_reason_stop,
                "actual_output": actual_output,
                "actual_hours": str(auto_actual_hours),
                "auto_actual_output": auto_actual_output,
                "auto_actual_hours": auto_actual_hours,
            })

        if time_difference < -0.0167:
            is_overtime = True
            time_difference = abs(time_difference)
            need_reason_explanation = True
        elif time_difference > 0.0167:
            is_overtime = False
            need_reason_explanation = True
        else:
            is_overtime = False
            need_reason_explanation = False

        if need_reason_explanation:
            # ===== SHARED REASON STOPS (tanpa maintenance) =====
            waiting_materials_shared = request.POST.get("waiting_materials_shared", 0)
            meeting_shared = request.POST.get("meeting_shared", 0)
            others_shared = request.POST.get("others_shared", 0)

            total_shared_time = (
                float(waiting_materials_shared or 0) +
                float(meeting_shared or 0) +
                float(others_shared or 0)
            )

            # ===== PER BJO REASON STOPS =====
            total_per_bjo_time = 0
            bjo_reason_data = {}

            for bjo_item in bjos_data:
                bjo_id = bjo_item['id']
                reject = request.POST.get(f"reject_{bjo_id}", 0)
                cutback = request.POST.get(f"cutback_{bjo_id}", 0)
                change_over = request.POST.get(f"change_over_{bjo_id}", 0)
                change_over_comment = request.POST.get(f"change_over_comment_{bjo_id}", "").strip()
                rejected_joints_str = request.POST.get(f"rejected_joints_{bjo_id}", "").strip()
                rejected_joints = [j.strip() for j in rejected_joints_str.split(",") if j.strip()]

                # Per-BJO maintenance
                maint_duration = float(request.POST.get(f"maint_duration_{bjo_id}", 0) or 0)
                maint_cost = float(request.POST.get(f"maint_cost_{bjo_id}", 0) or 0)
                maint_issue = request.POST.get(f"maint_issue_{bjo_id}", "").strip()

                # change_over + maint_duration keduanya masuk total per BJO
                total_per_bjo_time += float(change_over or 0) + maint_duration

                bjo_reason_data[bjo_id] = {
                    'reject': int(reject or 0),
                    'cutback': int(cutback or 0),
                    'change_over': float(change_over or 0),
                    'change_over_comment': change_over_comment,
                    'rejected_joints': rejected_joints,
                    'maint_duration': maint_duration,
                    'maint_cost': maint_cost,
                    'maint_issue': maint_issue,
                }

            total_reason_time = total_shared_time + total_per_bjo_time

            # Validation: total must match time_difference
            reason_type = "overtime" if is_overtime else "sisa waktu"
            if abs(total_reason_time - time_difference) > 0.0167:
                messages.error(
                    request,
                    f"Total waktu reason stop ({total_reason_time:.2f} jam) HARUS PAS "
                    f"dengan {reason_type} ({time_difference:.2f} jam). "
                    f"Tidak boleh lebih, tidak boleh kurang! "
                    f"(Shared: {total_shared_time:.2f} jam + Per BJO: {total_per_bjo_time:.2f} jam)"
                )
                return render(request, "weld/final.html", {
                    "header": header,
                    "total_qty": total_qty,
                    "total_hours": round(total_hours, 2),
                    "booked_duration": booked_duration,
                    "time_difference": round(time_difference, 2),
                    "need_reason_explanation": need_reason_explanation,
                    "is_overtime": is_overtime,
                    "bjos_data": bjos_data,
                    "existing_shared_reason_stop": existing_shared_reason_stop,
                    "actual_output": actual_output,
                    "actual_hours": actual_hours,
                    "auto_actual_output": auto_actual_output,
                    "auto_actual_hours": auto_actual_hours,
                })

            # ===== SAVE SHARED REASON STOP =====
            WeldReasonStop.objects.filter(Reff=header, bjo=None).delete()
            WeldReasonStop.objects.create(
                Reff=header,
                bjo=None,
                bjo_number=None,
                joint_number=None,
                waiting_materials=float(waiting_materials_shared or 0),
                meeting=float(meeting_shared or 0),
                others=float(others_shared or 0),
                maintenance=None,
                reject=0,
                cutback=0,
                change_over=0,
                change_over_comment='',
            )

            # ===== SAVE PER BJO REASON STOPS + MAINTENANCE =====
            for bjo_item in bjos_data:
                bjo_id = bjo_item['id']
                bjo_obj = JobHeader.objects.get(id=bjo_id)
                reason_data = bjo_reason_data.get(bjo_id, {})

                rejected_joints = reason_data.get('rejected_joints', [])
                reject_count = reason_data.get('reject', 0)
                cutback = reason_data.get('cutback', 0)
                change_over = reason_data.get('change_over', 0)
                change_over_comment = reason_data.get('change_over_comment', '')
                maint_duration = reason_data.get('maint_duration', 0)
                maint_cost = reason_data.get('maint_cost', 0)
                maint_issue = reason_data.get('maint_issue', '')

                # Handle Maintenance object per BJO
                maintenance_obj = None
                if maint_duration > 0:
                    maint_issue_final = maint_issue or f"Maintenance - BJO {bjo_obj.bjo} - {header.machine.name}"
                    try:
                        existing_maint = Maintenance.objects.filter(
                            weld_machine=header,
                            bjo=bjo_obj
                        ).first()

                        if existing_maint:
                            existing_maint.duration = maint_duration
                            existing_maint.cost = maint_cost
                            existing_maint.issue = maint_issue_final
                            existing_maint.save()
                            maintenance_obj = existing_maint
                        else:
                            maintenance_obj = Maintenance.objects.create(
                                weld_machine=header,
                                bjo=bjo_obj,
                                issue=maint_issue_final,
                                duration=maint_duration,
                                cost=maint_cost,
                            )
                    except Exception as e:
                        messages.error(request, f"Error menyimpan data maintenance BJO {bjo_obj.bjo}: {e}")
                else:
                    # Hapus maintenance lama jika duration dikosongkan
                    Maintenance.objects.filter(weld_machine=header, bjo=bjo_obj).delete()

                # Cleanup + create WeldReasonStop per BJO
                WeldReasonStop.objects.filter(Reff=header, bjo=bjo_obj).delete()

                if reject_count > 0 or cutback > 0 or change_over > 0 or maint_duration > 0:
                    rejected_joints_str = ','.join(rejected_joints) if rejected_joints else ''
                    WeldReasonStop.objects.create(
                        Reff=header,
                        bjo=bjo_obj,
                        bjo_number=bjo_obj.bjo,
                        joint_number=None,
                        reject=reject_count,
                        rejected_joints=rejected_joints_str,
                        cutback=cutback,
                        change_over=change_over,
                        change_over_comment=change_over_comment,
                        maintenance=maintenance_obj,
                        waiting_materials=None,
                        meeting=None,
                        others=None,
                    )

        # ===== SAVE FINALIZATION =====
        header.actual_output = actual_output
        header.actual_hours = actual_hours
        header.comment = comment
        header.is_posted = True
        header.save()

        messages.success(request, "Finalisasi welding record berhasil disimpan.")
        return redirect("weld_list")

    # ===== GET REQUEST =====
    total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()

    return render(request, "weld/final.html", {
        "header": header,
        "total_qty": total_qty,
        "total_hours": round(total_hours, 2),
        "booked_duration": booked_duration,
        "time_difference": 0,
        "need_reason_explanation": False,
        "is_overtime": False,
        "bjos_data": bjos_data,
        "existing_shared_reason_stop": existing_shared_reason_stop,
        "auto_actual_output": auto_actual_output,
        "auto_actual_hours": auto_actual_hours,
    })
    
def weld_report(request, header_id):
    """View untuk menampilkan laporan welding dalam format mirip form manual"""
    header = get_object_or_404(WeldHeader, pk=header_id)
    detail_list = WeldDetail.objects.filter(Reff=header).order_by('start_time', 'id')
    
    # Hitung durasi untuk setiap detail dan ambil data NCR
    for detail in detail_list:
        detail.duration_minutes = calculate_time_duration(detail.start_time, detail.stop_time)
        
        # Ambil data NCR untuk detail ini
        ncr_record = WeldNcr.objects.filter(serial=detail).first()
        if ncr_record:
            detail.ncr_status = "NCR"
            detail.ncr_reason = ncr_record.reason
        else:
            detail.ncr_status = "-"
            detail.ncr_reason = ""
    
    # Ambil data reason stop jika ada
    reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
    
    # Ambil data consumable jika ada
    consumable = WeldConsumsion.objects.filter(Reff=header).first()
    
    # Siapkan data summary berdasarkan shift
    is_shift_1 = header.shift and ('1' in header.shift.name or 'satu' in header.shift.name.lower() or 'first' in header.shift.name.lower())
    is_shift_2 = header.shift and ('2' in header.shift.name or 'dua' in header.shift.name.lower() or 'second' in header.shift.name.lower())
    
    # Hitung total NCR dari detail
    total_ncr = sum(1 for detail in detail_list if hasattr(detail, 'ncr_status') and detail.ncr_status == "NCR")
    
    # MAINTENANCE DATA COLLECTION
    maintenance_duration_1 = 0
    maintenance_duration_2 = 0
    maintenance_info = ""
    
    # Ambil data maintenance dari reason_stops
    if reason_stops and hasattr(reason_stops, 'maintenance') and reason_stops.maintenance:
        maintenance_duration = reason_stops.maintenance.duration if reason_stops.maintenance.duration else 0
        maintenance_issue = reason_stops.maintenance.issue if reason_stops.maintenance.issue else "Maintenance"
        maintenance_info = f"{maintenance_issue} ({maintenance_duration}h)"
        
        # Assign ke shift yang sesuai
        if is_shift_1:
            maintenance_duration_1 = maintenance_duration
        elif is_shift_2:
            maintenance_duration_2 = maintenance_duration
    
    # ALTERNATIF: Jika maintenance tidak ada di reason_stops,
    # cari dari tabel Maintenance langsung berdasarkan WeldHeader
    if not maintenance_info:
        daily_maintenances = Maintenance.objects.filter(
            weld_machine=header  # Filter berdasarkan weld_machine field
        ).order_by('-id')  # Ambil yang terbaru
        
        if daily_maintenances.exists():
            # Ambil maintenance pertama (terbaru)
            latest_maintenance = daily_maintenances.first()
            maintenance_duration = latest_maintenance.duration if latest_maintenance.duration else 0
            maintenance_issue = latest_maintenance.issue if latest_maintenance.issue else "Maintenance"
            maintenance_info = f"{maintenance_issue} ({maintenance_duration}h)"
            
            # Assign ke shift yang sesuai
            if is_shift_1:
                maintenance_duration_1 = maintenance_duration
            elif is_shift_2:
                maintenance_duration_2 = maintenance_duration
    else:
        # Jika sudah ada maintenance_info dari reason_stops, ambil semua maintenance untuk header ini
        daily_maintenances = Maintenance.objects.filter(weld_machine=header)
    
    # Hitung total maintenance duration dari semua record maintenance untuk WeldHeader ini
    if not 'daily_maintenances' in locals():
        daily_maintenances = Maintenance.objects.filter(weld_machine=header)
    
    total_maintenance_duration = sum(m.duration for m in daily_maintenances if m.duration)
    
    # PERHITUNGAN TOTAL HOURS YANG BENAR (MIRIP THREADING)
    # Fungsi helper untuk mengkonversi nilai ke float, return 0 jika tidak valid
    def safe_float(value):
        if value is None or value == '' or value == '-':
            return 0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0
    
    # Hitung total hours untuk shift 1
    total_hours_1 = 0
    if is_shift_1:
        prod_time_1 = safe_float(header.actual_hours)
        waiting_materials_1 = safe_float(reason_stops.waiting_materials if reason_stops else 0)
        meeting_1 = safe_float(reason_stops.meeting if reason_stops else 0)
        maintenance_1 = safe_float(maintenance_duration_1)
        others_1 = safe_float(reason_stops.others if reason_stops else 0)
        
        total_hours_1 = prod_time_1 + waiting_materials_1 + meeting_1 + maintenance_1 + others_1
    
    # Hitung total hours untuk shift 2
    total_hours_2 = 0
    if is_shift_2:
        prod_time_2 = safe_float(header.actual_hours)
        waiting_materials_2 = safe_float(reason_stops.waiting_materials if reason_stops else 0)
        meeting_2 = safe_float(reason_stops.meeting if reason_stops else 0)
        maintenance_2 = safe_float(maintenance_duration_2)
        others_2 = safe_float(reason_stops.others if reason_stops else 0)
        
        total_hours_2 = prod_time_2 + waiting_materials_2 + meeting_2 + maintenance_2 + others_2
    
    summary_data = {
        # Shift 1 data - hanya diisi jika header adalah shift 1
        'total_output_1': header.actual_output if is_shift_1 else '',
        'reject_1': reason_stops.reject if (reason_stops and is_shift_1) else '',
        'cutback_1': reason_stops.cutback if (reason_stops and is_shift_1) else '',
        'waiting_materials_1': reason_stops.waiting_materials if (reason_stops and is_shift_1) else '',
        'meeting_1': reason_stops.meeting if (reason_stops and is_shift_1) else '',
        'prod_time_1': header.actual_hours if is_shift_1 else '',
        'maintenance_1': maintenance_duration_1 if maintenance_duration_1 else '',
        'others_1': reason_stops.others if (reason_stops and is_shift_1) else '',
        'ncr_1': total_ncr if is_shift_1 else '',
        'total_hours_1': total_hours_1 if is_shift_1 else '',  # PERBAIKAN: Gunakan total yang dihitung
        
        # Shift 2 data - hanya diisi jika header adalah shift 2
        'total_output_2': header.actual_output if is_shift_2 else '',
        'reject_2': reason_stops.reject if (reason_stops and is_shift_2) else '',
        'cutback_2': reason_stops.cutback if (reason_stops and is_shift_2) else '',
        'waiting_materials_2': reason_stops.waiting_materials if (reason_stops and is_shift_2) else '',
        'meeting_2': reason_stops.meeting if (reason_stops and is_shift_2) else '',
        'prod_time_2': header.actual_hours if is_shift_2 else '',
        'maintenance_2': maintenance_duration_2 if maintenance_duration_2 else '',
        'others_2': reason_stops.others if (reason_stops and is_shift_2) else '',
        'ncr_2': total_ncr if is_shift_2 else '',
        'total_hours_2': total_hours_2 if is_shift_2 else '',  # PERBAIKAN: Gunakan total yang dihitung
        
        # General data
        'current_shift': header.shift.name if header.shift else '',
        'is_shift_1': is_shift_1,
        'is_shift_2': is_shift_2,
        
        # INFO MAINTENANCE
        'maintenance_info': maintenance_info,
        'total_maintenance_duration': total_maintenance_duration,
        'daily_maintenances': daily_maintenances,
    }
    
    # Siapkan data consumable berdasarkan shift
    consumable_data = {
        # Default values
        'wire_1': '',
        'flux_1': '',
        'granding_1': '',
        'cutting_1': '',
        'others_1': '',
        'wire_2': '',
        'flux_2': '',
        'granding_2': '',
        'cutting_2': '',
        'others_2': '',
    }
    
    # Isi data consumable berdasarkan shift jika ada record consumable
    if consumable:
        if is_shift_1:
            consumable_data.update({
                'wire_1': consumable.wire or '-',
                'flux_1': consumable.flux or '-',
                'granding_1': consumable.granding or '-',
                'cutting_1': consumable.cutting or '-',
                'others_1': consumable.others or '-',
            })
        elif is_shift_2:
            consumable_data.update({
                'wire_2': consumable.wire or '-',
                'flux_2': consumable.flux or '-',
                'granding_2': consumable.granding or '-',
                'cutting_2': consumable.cutting or '-',
                'others_2': consumable.others or '-',
            })
    
    context = {
        'header': header,
        'detail_list': detail_list,
        'summary': summary_data,
        'consumable': consumable_data,
        'reason_stops': reason_stops,
        'consumable_record': consumable,
        'total_ncr': total_ncr,
        'maintenance_records': daily_maintenances,
    }
    
    return render(request, 'weld/report.html', context)

def weld_pdf(request):
    """Generate PDF untuk WeldHeader dengan filter yang sama seperti weld_list - FIXED VERSION"""
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    headers = WeldHeader.objects.select_related(
        'machine', 
        'shift', 
        'operator', 
        'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    headers = headers.order_by('-date', '-id')

    # PERBAIKAN: Hitung actual_hours DAN actual_output yang benar
    for header in headers:
        if not header.is_posted:
            detail_qs = WeldDetail.objects.filter(Reff=header)
            total_hours = 0
            
            for detail in detail_qs:
                if detail.start_time and detail.stop_time:
                    duration_hours = calculate_time_duration(detail.start_time, detail.stop_time)
                    if duration_hours:
                        total_hours += duration_hours
            
            header.calculated_actual_hours = round(total_hours, 2)
            
            # FIXED: Gunakan SUM dari output, bukan COUNT
            total_output = detail_qs.aggregate(Sum('output'))['output__sum'] or 0
            header.calculated_actual_output = round(total_output, 2)
        else:
            header.calculated_actual_hours = float(header.actual_hours) if header.actual_hours else 0
            header.calculated_actual_output = float(header.actual_output) if header.actual_output else 0

    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))
    today = date.today()

    template_path = 'weld/pdf.html'
    context = {
        'headers': headers,
        'logo_url': logo_url,
        'today': today,
        'query': query,
        'filter_machine': filter_machine,
        'filter_date': filter_date,
        'filter_status': filter_status,
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="weld_record_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Terjadi kesalahan saat membuat PDF', status=500)
    return response

@welding_ncr_access_required
def weld_ncr_list(request):
    query = request.GET.get('q', '')
    items = WeldNcr.objects.select_related(
        'serial__Reff__machine', 
        'serial__bjo'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Weld Header fields - menggunakan field yang benar dari WeldHeader
            Q(serial__Reff__machine__name__icontains=query) |
            Q(serial__Reff__date__icontains=query) |
            Q(serial__Reff__operator__name__icontains=query) |
            Q(serial__Reff__shift__name__icontains=query) |
            # Job Header fields - menggunakan field yang benar dari JobHeader
            Q(serial__bjo__bjo__icontains=query) |
            Q(serial__bjo__customer__icontains=query) |
            Q(serial__bjo__bt__icontains=query) |
            Q(serial__bjo__product__icontains=query) |
            # Weld Detail fields
            Q(serial__joint_number__icontains=query) |
            # Weld NCR fields
            Q(reason__icontains=query) |
            Q(disposition__icontains=query) |
            Q(action__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'weld_ncr_list'
    }
    return render(request, 'weld/ncr/list.html', context)

@welding_ncr_access_required
def weld_ncr_edit(request, id):
    item = get_object_or_404(WeldNcr, id=id)
    
    if request.method == 'POST':
        # Update field yang bisa diedit
        item.reason = request.POST.get('reason')
        item.disposition = request.POST.get('disposition')
        item.action = request.POST.get('action')
        
        # Validasi - pastikan setidaknya ada satu field yang diisi
        if not item.reason and not item.disposition and not item.action:
            messages.error(request, "Minimal satu field (Reason, Disposition, atau Action) harus diisi.")
            return redirect('weld_ncr_edit', id=id)
        
        item.save()
        messages.success(request, "Data Welding NCR berhasil diperbarui.")
        return redirect('weld_ncr_list')
    
    return render(request, 'weld/ncr/edit.html', {
        'item': item,
        'active_menu': 'weld_ncr_list'
    })

@welding_ncr_access_required
def weld_ncr_create(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                serial_id = request.POST.get('serial')
                reason = request.POST.get('reason', '').strip()
                disposition = request.POST.get('disposition', '').strip()
                action = request.POST.get('action', '').strip()

                # Validasi serial (WeldDetail) wajib
                if not serial_id:
                    messages.error(request, "Weld Detail wajib dipilih.")
                    return redirect('weld_ncr_create')

                try:
                    weld_detail = WeldDetail.objects.get(id=serial_id)
                except WeldDetail.DoesNotExist:
                    messages.error(request, "Weld Detail yang dipilih tidak valid.")
                    return redirect('weld_ncr_create')

                existing_ncr = WeldNcr.objects.filter(serial=weld_detail).first()
                if existing_ncr:
                    messages.warning(
                        request, 
                        f"NCR untuk Weld Detail (Joint: {weld_detail.joint_number}) sudah ada. "
                        f"Silakan edit NCR yang sudah ada."
                    )
                    return redirect('weld_ncr_edit', ncr_id=existing_ncr.id)
                weld_ncr = WeldNcr.objects.create(
                    serial=weld_detail,
                    reason=reason if reason else None,
                    disposition=disposition if disposition else None,
                    action=action if action else None,
                )

                if weld_detail.joint_number and weld_detail.bjo:
                    if weld_detail.pin_or_box == 'BOX':
                        BoxProtector.objects.filter(
                            serial_number=weld_detail.joint_number, 
                            bjo=weld_detail.bjo
                        ).update(is_ncr=True)
                    elif weld_detail.pin_or_box == 'PIN':
                        PinProtector.objects.filter(
                            serial_number=weld_detail.joint_number, 
                            bjo=weld_detail.bjo
                        ).update(is_ncr=True)
                    SerialNumber.objects.filter(
                        joint_number=weld_detail.joint_number, 
                        bjo=weld_detail.bjo
                    ).update(is_ncr=True)

                messages.success(
                    request, 
                    f"WeldNcr berhasil dibuat untuk Joint Number '{weld_detail.joint_number}'. "
                    f"Status NCR pada Serial Number telah diupdate menjadi True."
                )
                return redirect('weld_ncr_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('weld_ncr_create')


    available_details = WeldDetail.objects.filter(
        weldncr__isnull=True,
        is_uncompleted=False
    ).select_related(
        'Reff__machine',
        'bjo'
    ).order_by('-Reff__date', '-created_at')  # URUTKAN BERDASARKAN TANGGAL TERBARU

    context = {
        'available_details': available_details,
        'active_menu': 'weld_ncr_list',
    }
    return render(request, 'weld/ncr/create.html', context)

@welding_ncr_access_required
def weld_ncr_delete(request, id):
    item = get_object_or_404(WeldNcr, id=id)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                weld_info = ""
                if item.serial and item.serial.Reff:
                    machine_name = item.serial.Reff.machine.name if item.serial.Reff.machine else "Unknown"
                    date_str = item.serial.Reff.date.strftime('%d/%m/%Y') if item.serial.Reff.date else "Unknown"
                    weld_info = f"{machine_name} - {date_str}"
                else:
                    weld_info = "Welding NCR"
                joint_info = f" (Joint: {item.serial.joint_number})" if item.serial and item.serial.joint_number else ""
                weld_detail = item.serial
                
                if weld_detail and weld_detail.joint_number and weld_detail.bjo:
                    if weld_detail.pin_or_box == 'BOX':
                        BoxProtector.objects.filter(
                            serial_number=weld_detail.joint_number, 
                            bjo=weld_detail.bjo
                        ).update(is_ncr=False)
                    elif weld_detail.pin_or_box == 'PIN':
                        PinProtector.objects.filter(
                            serial_number=weld_detail.joint_number, 
                            bjo=weld_detail.bjo
                        ).update(is_ncr=False)
                    
                    SerialNumber.objects.filter(
                        joint_number=weld_detail.joint_number, 
                        bjo=weld_detail.bjo
                    ).update(is_ncr=False)
                
                # Hapus data NCR
                item.delete()
                
                messages.success(
                    request, 
                    f'Data Welding NCR {weld_info}{joint_info} berhasil dihapus. '
                    f'Status NCR pada Serial Number telah dikembalikan ke normal.'
                )
                return redirect('weld_ncr_list')
                
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('weld_ncr_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('weld_ncr_list')

@welding_consumption_access_required
def weld_consumption_list(request):
    query = request.GET.get('q', '')
    items = WeldConsumsion.objects.select_related(
        'Reff__machine', 
        'Reff__operator',
        'Reff__shift'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Weld Header fields
            Q(Reff__machine__name__icontains=query) |
            Q(Reff__date__icontains=query) |
            Q(Reff__operator__name__icontains=query) |
            Q(Reff__shift__name__icontains=query) |
            # Weld Consumption fields
            Q(wire__icontains=query) |
            Q(flux__icontains=query) |
            Q(granding__icontains=query) |
            Q(cutting__icontains=query) |
            Q(others__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'weld_consumption_list'
    }
    return render(request, 'weld/consumption/list.html', context)

@welding_consumption_access_required
def weld_consumption_edit(request, pk):
    item = get_object_or_404(WeldConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data - Weld Header tidak bisa diubah, jadi tidak perlu diupdate
            wire = request.POST.get('wire') or None
            flux = request.POST.get('flux') or None
            granding = request.POST.get('granding') or None
            cutting = request.POST.get('cutting') or None
            others = request.POST.get('others') or None

            # Update WeldConsumsion
            item.wire = wire
            item.flux = flux
            item.granding = granding
            item.cutting = cutting
            item.others = others
            item.save()

            messages.success(request, 'Data Welding Consumption berhasil diperbarui.')
            return redirect('weld_consumption_list')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
    
    context = {
        'item': item,
        'active_menu': 'weld_consumption_list'
    }
    return render(request, 'weld/consumption/edit.html', context)

@welding_consumption_access_required
def weld_consumption_delete(request, pk):
    item = get_object_or_404(WeldConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Simpan informasi untuk pesan sebelum menghapus
            weld_info = ""
            if item.Reff:
                machine_name = item.Reff.machine.name if item.Reff.machine else "Unknown"
                date_str = item.Reff.date.strftime('%d/%m/%Y') if item.Reff.date else "Unknown"
                weld_info = f"{machine_name} - {date_str}"
            else:
                weld_info = "Welding Consumption"
            
            # Hapus data
            item.delete()
            
            messages.success(request, f'Data Welding Consumption {weld_info} berhasil dihapus.')
            return redirect('weld_consumption_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('weld_consumption_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('weld_consumption_list')

@threading_report_access_required
def thread_report_oee(request):
    # Get date range from request or default to current week
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not start_date or not end_date:
        # Default to current week (Sunday to Saturday)
        today = datetime.now().date()
        
        # Calculate days since last Sunday
        # Sunday = 6, Monday = 0, Tuesday = 1, ..., Saturday = 5
        days_since_sunday = (today.weekday() + 1) % 7
        
        # Find the Sunday of current week
        start_date = today - timedelta(days=days_since_sunday)
        # End date is Saturday (6 days after Sunday)
        end_date = start_date + timedelta(days=6)
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        # Auto-adjust to Sunday-Saturday week if needed
        # Find the Sunday that contains or precedes the start_date
        days_since_sunday = (start_date.weekday() + 1) % 7
        adjusted_start = start_date - timedelta(days=days_since_sunday)
        adjusted_end = adjusted_start + timedelta(days=6)
        
        # Use adjusted dates if the original range doesn't span exactly 7 days
        if (end_date - start_date).days != 6:
            start_date = adjusted_start
            end_date = adjusted_end
    
    # Calculate week number
    week_number = start_date.isocalendar()[1] + 1
    
    # Get all machines that are threading type
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    machines = Machine.objects.filter(process_type=threading_process)
    
    # Create date range (Sunday to Saturday)
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timedelta(days=1)
    
    # Ensure we have exactly 7 days
    assert len(date_range) == 7, "Week should contain exactly 7 days"
    
    # Get threading headers for the date range (INCLUDE NON-POSTED RECORDS)
    thread_headers = ThreadHeader.objects.filter(
        date__range=[start_date, end_date]
    ).select_related('machine', 'operator', 'shift', 'booked_hours')
    
    # Step 1: Calculate maximum work orders per day (count work_order + shift combination)
    columns_per_day = {}
    
    for date in date_range:
        max_work_orders_for_date = 0
        
        # Check each machine for this date to find the maximum work orders
        for machine in machines:
            work_order_shift_combinations = []
            headers_for_machine_date = thread_headers.filter(machine=machine, date=date)
            
            for header in headers_for_machine_date:
                details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        # Create unique identifier: work_order + shift
                        work_order_shift_key = f"{detail.bjo.bjo}_{header.shift.name if header.shift else 'NO_SHIFT'}"
                        if work_order_shift_key not in work_order_shift_combinations:
                            work_order_shift_combinations.append(work_order_shift_key)
            
            # Update max for this date
            max_work_orders_for_date = max(max_work_orders_for_date, len(work_order_shift_combinations))
        
        # Store column count for this date (minimum 1)
        columns_per_day[date] = max(1, max_work_orders_for_date)
    
    # Step 2: Initialize summary data structure
    summary_data = {
        'daily_data': [],
        'weekly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_absorption_hours': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Initialize daily summary with dynamic columns per day
    for date in date_range:
        summary_data['daily_data'].append({
            'date': date,
            'columns_count': columns_per_day[date],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'absorption_hours': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        })
    
    # Step 3: Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'daily_data': [],
            'weekly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_absorption_hours': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each date for this machine
        for date_index, date in enumerate(date_range):
            columns_for_this_date = columns_per_day[date]
            
            # Get work orders for this machine and date
            headers_for_date = thread_headers.filter(machine=machine, date=date)
            
            # Get booked hours from header - per shift
            booked_hours_by_shift = {}
            for header in headers_for_date:
                shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                if header.booked_hours and header.booked_hours.duration:
                    if shift_name not in booked_hours_by_shift:
                        booked_hours_by_shift[shift_name] = 0
                    booked_hours_by_shift[shift_name] += float(header.booked_hours.duration)
            
            # Total booked hours for the day
            booked_hours_from_header = sum(booked_hours_by_shift.values())
            
            # Collect work order data - separate by work_order + shift
            work_order_shift_list = []  # List of (work_order, shift_name) tuples
            work_order_shift_data = {}  # Key: (work_order, shift_name)
            
            for header in headers_for_date:
                shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                details = ThreadDetail.objects.filter(Reff=header).select_related('bjo', 'bjo__size', 'bjo__conn')
                
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        work_order = detail.bjo.bjo
                        
                        # Create unique key with shift
                        work_order_shift_key = (work_order, shift_name)
                        
                        if work_order_shift_key not in work_order_shift_list:
                            work_order_shift_list.append(work_order_shift_key)
                        
                        if work_order_shift_key not in work_order_shift_data:
                            # Clean size display
                            size_display = str(detail.bjo.size) if detail.bjo.size else ''
                            if size_display:
                                size_display = size_display.replace('THREADING', '').replace('WELDING', '').strip()
                            
                            work_order_shift_data[work_order_shift_key] = {
                                'header': header,
                                'shift': shift_name,
                                'details': [],
                                'bjo_obj': detail.bjo,  # Store BJO object for later use
                                'client': detail.bjo.customer if detail.bjo.customer else '',
                                'size': size_display,
                                'connection': detail.bjo.conn.name if detail.bjo.conn else '',
                                'cycle_time': str(detail.ct) if detail.ct else '',
                                'price_book': str(detail.pb) if detail.pb else '',
                                'actual_hours': 0,
                                'output_qty': 0,
                                'non_recordable_time': 0,
                                'booked_hours_for_shift': 0,
                                'is_posted': header.is_posted,  # Track if header is posted
                            }
                        work_order_shift_data[work_order_shift_key]['details'].append(detail)
            
            # Sort work_order_shift_list by shift order (SHIFT 1 first, then SHIFT 2, then others)
            def shift_sort_key(item):
                work_order, shift_name = item
                # Priority: SHIFT 1 = 1, SHIFT 2 = 2, others = 3
                if 'SHIFT 1' in shift_name or 'Shift 1' in shift_name:
                    return (1, work_order)
                elif 'SHIFT 2' in shift_name or 'Shift 2' in shift_name:
                    return (2, work_order)
                else:
                    return (3, shift_name, work_order)
            
            work_order_shift_list.sort(key=shift_sort_key)
            
            # Calculate actual hours, non-recordable time, and output qty for each work order-shift combination
            for work_order_shift_key in work_order_shift_data:
                wo_data = work_order_shift_data[work_order_shift_key]
                details = wo_data['details']
                header = wo_data['header']
                bjo_obj = wo_data['bjo_obj']
                
                total_hours = 0
                total_output = 0
                
                # Calculate hours from start/stop times using calculate_time_duration
                for detail in details:
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours is not None:
                            total_hours += hours
                    
                    # Calculate output from field output in detail
                    if detail.output:
                        total_output += float(detail.output)
                
                # Get shared reason stops (bjo=None)
                shared_reason_stops = TreadReasonStop.objects.filter(Reff=header, bjo=None).first()
                
                # Get per-BJO reason stops
                bjo_reason_stops = TreadReasonStop.objects.filter(Reff=header, bjo=bjo_obj).first()

                # ✅ FIX: Calculate non-recordable time
                # Shared: waiting_materials + meeting + others (NO maintenance from shared)
                # Per-BJO: change_over + maintenance.duration (dari per-BJO)
                total_non_recordable = 0
                if shared_reason_stops:
                    total_non_recordable = (
                        float(shared_reason_stops.waiting_materials or 0) +
                        float(shared_reason_stops.meeting or 0) +
                        float(shared_reason_stops.others or 0)
                        # ✅ maintenance TIDAK diambil dari shared lagi
                    )
                
                # Add change_over dari per-BJO reason stops
                if bjo_reason_stops and bjo_reason_stops.change_over:
                    total_non_recordable += float(bjo_reason_stops.change_over)

                # ✅ FIX: Add breakdown/maintenance dari per-BJO reason stops
                if bjo_reason_stops and bjo_reason_stops.maintenance:
                    total_non_recordable += float(bjo_reason_stops.maintenance.duration or 0)
                
                wo_data['actual_hours'] = total_hours
                wo_data['output_qty'] = total_output
                wo_data['non_recordable_time'] = total_non_recordable
                wo_data['bjo_reason_stops'] = bjo_reason_stops  # Store for later use
                wo_data['shared_reason_stops'] = shared_reason_stops  # Store for later use
            
            # DISTRIBUSI BOOKED HOURS - METODE PLANNED HOURS (Output × CT)
            planned_hours_per_shift = {}
            work_orders_per_shift = {}
            
            for work_order_shift_key, wo_data in work_order_shift_data.items():
                shift_name = wo_data['shift']
                
                if shift_name not in planned_hours_per_shift:
                    planned_hours_per_shift[shift_name] = 0
                    work_orders_per_shift[shift_name] = []
                
                # Calculate planned hours = Output × Cycle Time
                planned_hours_for_wo = 0
                if wo_data['output_qty'] > 0 and wo_data['cycle_time']:
                    try:
                        cycle_time = float(wo_data['cycle_time'])
                        if cycle_time > 0:
                            planned_hours_for_wo = wo_data['output_qty'] * cycle_time
                    except (ValueError, TypeError):
                        planned_hours_for_wo = 0
                
                wo_data['planned_hours'] = planned_hours_for_wo
                planned_hours_per_shift[shift_name] += planned_hours_for_wo
                work_orders_per_shift[shift_name].append(work_order_shift_key)
            
            # Distribute booked hours to each work order based on planned hours
            for shift_name, total_planned_hours in planned_hours_per_shift.items():
                booked_hours_for_shift = booked_hours_by_shift.get(shift_name, 0)
                work_orders_in_shift = work_orders_per_shift[shift_name]
                
                if total_planned_hours > 0:
                    # PROPORTIONAL distribution based on planned hours
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        proportion = wo_data['planned_hours'] / total_planned_hours
                        wo_data['booked_hours_for_shift'] = booked_hours_for_shift * proportion
                else:
                    # EQUAL distribution if no planned hours
                    num_work_orders = len(work_orders_in_shift)
                    allocated_hours = booked_hours_for_shift / num_work_orders if num_work_orders > 0 else 0
                    
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        wo_data['booked_hours_for_shift'] = allocated_hours
            
            # Initialize daily data with correct column count for this date
            daily_data = {
                'date': date,
                'columns_count': columns_for_this_date,
                'booked_hours_header': booked_hours_from_header,
                'booked_hours_distributed': [0] * columns_for_this_date,
                'work_orders': [''] * columns_for_this_date,
                'shifts': [''] * columns_for_this_date,
                'clients': [''] * columns_for_this_date,
                'sizes': [''] * columns_for_this_date,
                'connections': [''] * columns_for_this_date,
                'cycle_times': [''] * columns_for_this_date,
                'price_books': [''] * columns_for_this_date,
                'working_hours': [0] * columns_for_this_date,
                'planned_production': [0] * columns_for_this_date,
                'output_qty': [0] * columns_for_this_date,
                'rejects': [0] * columns_for_this_date,
                'cutbacks': [0] * columns_for_this_date,
                'oee': [0] * columns_for_this_date,
                'reject_rate': [0] * columns_for_this_date,
                'absorption_hours': [0] * columns_for_this_date,
                'operating_hours': [0] * columns_for_this_date,
                'non_recorded_time': [0] * columns_for_this_date,
                'wait_material': [0] * columns_for_this_date,
                'meetings': [0] * columns_for_this_date,
                'breakdown': [0] * columns_for_this_date,
                'change_over': [0] * columns_for_this_date,
                'availability': [0] * columns_for_this_date,
                'performance': [0] * columns_for_this_date,
                'quality': [0] * columns_for_this_date,
                'total_working_hours': 0,
                'total_output_qty': 0,
                'is_posted': [True] * columns_for_this_date,  # Track posted status for each column
            }
            
            # Fill data for each work order-shift combination
            for i, work_order_shift_key in enumerate(work_order_shift_list):
                if i < columns_for_this_date and work_order_shift_key in work_order_shift_data:
                    wo_data = work_order_shift_data[work_order_shift_key]
                    header = wo_data['header']
                    work_order, shift_name = work_order_shift_key
                    bjo_reason_stops = wo_data.get('bjo_reason_stops')
                    shared_reason_stops = wo_data.get('shared_reason_stops')
                    
                    daily_data['work_orders'][i] = work_order
                    daily_data['shifts'][i] = shift_name
                    daily_data['clients'][i] = wo_data['client']
                    daily_data['sizes'][i] = wo_data['size']
                    daily_data['connections'][i] = wo_data['connection']
                    daily_data['cycle_times'][i] = wo_data['cycle_time']
                    daily_data['price_books'][i] = wo_data['price_book']
                    daily_data['working_hours'][i] = wo_data['actual_hours']
                    daily_data['output_qty'][i] = wo_data['output_qty']
                    daily_data['booked_hours_distributed'][i] = wo_data['booked_hours_for_shift']
                    daily_data['is_posted'][i] = wo_data['is_posted']  # Set posted status
                    
                    # Set reject and cutback from per-BJO reason stops
                    if bjo_reason_stops:
                        daily_data['rejects'][i] = float(bjo_reason_stops.reject or 0)
                        daily_data['cutbacks'][i] = float(bjo_reason_stops.cutback or 0)
                        daily_data['change_over'][i] = float(bjo_reason_stops.change_over or 0)
                    else:
                        daily_data['rejects'][i] = 0
                        daily_data['cutbacks'][i] = 0
                        daily_data['change_over'][i] = 0

                    # ✅ FIX: breakdown diambil dari per-BJO maintenance (bukan shared)
                    if bjo_reason_stops and bjo_reason_stops.maintenance:
                        daily_data['breakdown'][i] = float(bjo_reason_stops.maintenance.duration or 0)
                    else:
                        daily_data['breakdown'][i] = 0

                    # Set shared reason stops - wait_material dan meetings dibagi rata per WO dalam shift
                    # Get count of work orders in this shift for distribution
                    work_orders_in_shift_count = len([k for k in work_order_shift_list if k[1] == shift_name])
                    
                    if shared_reason_stops and work_orders_in_shift_count > 0:
                        daily_data['wait_material'][i] = float(shared_reason_stops.waiting_materials or 0) / work_orders_in_shift_count
                        daily_data['meetings'][i] = float(shared_reason_stops.meeting or 0) / work_orders_in_shift_count
                    else:
                        daily_data['wait_material'][i] = 0
                        daily_data['meetings'][i] = 0
                    
                    # Calculate downtime
                    total_downtime = (
                        daily_data['wait_material'][i] + 
                        daily_data['meetings'][i] + 
                        daily_data['breakdown'][i] + 
                        daily_data['change_over'][i]
                    )
                    daily_data['non_recorded_time'][i] = total_downtime
                    
                    # OEE CALCULATION
                    booked_hours_for_this_wo = wo_data['booked_hours_for_shift']
                    
                    try:
                        if (booked_hours_for_this_wo > 0 and 
                            daily_data['cycle_times'][i] and 
                            float(daily_data['cycle_times'][i]) > 0 and
                            daily_data['output_qty'][i] > 0):
                            
                            cycle_time = float(daily_data['cycle_times'][i])
                            output = daily_data['output_qty'][i]
                            rejects = daily_data['rejects'][i]
                            cutbacks = daily_data['cutbacks'][i]
                            
                            # Good Output = Output - Reject - Cutback
                            good_output = output - rejects - cutbacks
                            good_output = max(0, good_output)
                            
                            # OEE = ((Good Output × CT) / Booked Hours) × 100%
                            if booked_hours_for_this_wo > 0:
                                oee_value = ((good_output * cycle_time) / booked_hours_for_this_wo) * 100
                                oee_value = max(0, min(oee_value, 100))
                            else:
                                oee_value = 0
                            
                            daily_data['oee'][i] = round(oee_value, 2)
                            
                            # Clear availability, performance, quality karena tidak digunakan lagi
                            daily_data['availability'][i] = 0
                            daily_data['performance'][i] = 0
                            daily_data['quality'][i] = 0
                        else:
                            daily_data['availability'][i] = 0
                            daily_data['performance'][i] = 0
                            daily_data['quality'][i] = 0
                            daily_data['oee'][i] = 0
                    except (ZeroDivisionError, ValueError, TypeError):
                        daily_data['availability'][i] = 0
                        daily_data['performance'][i] = 0
                        daily_data['quality'][i] = 0
                        daily_data['oee'][i] = 0
                    
                    # Calculate operating hours
                    daily_data['operating_hours'][i] = max(0, daily_data['working_hours'][i] - daily_data['non_recorded_time'][i])
                    
                    # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
                    total_production = daily_data['output_qty'][i] + daily_data['rejects'][i] + daily_data['cutbacks'][i]
                    if total_production > 0:
                        daily_data['reject_rate'][i] = ((daily_data['rejects'][i] + daily_data['cutbacks'][i]) / total_production * 100)
                    else:
                        daily_data['reject_rate'][i] = 0
                    
                    # Calculate planned production based on distributed booked hours
                    if daily_data['cycle_times'][i] and booked_hours_for_this_wo > 0:
                        try:
                            cycle_time = float(daily_data['cycle_times'][i])
                            if cycle_time > 0:
                                daily_data['planned_production'][i] = booked_hours_for_this_wo / cycle_time
                        except (ValueError, TypeError):
                            daily_data['planned_production'][i] = 0
                    
                    # ABSORPTION HOURS: process_rate × (CT × Actual Output)
                    if daily_data['cycle_times'][i] and daily_data['output_qty'][i]:
                        try:
                            cycle_time = float(daily_data['cycle_times'][i])
                            output = daily_data['output_qty'][i]
                            
                            process_rate = 0
                            if machine.process_type and machine.process_type.rate:
                                process_rate = float(machine.process_type.rate)
                            
                            daily_data['absorption_hours'][i] = process_rate * (cycle_time * output)
                        except (ValueError, TypeError):
                            daily_data['absorption_hours'][i] = 0
                    else:
                        daily_data['absorption_hours'][i] = 0
                    
                    # ===== ONLY ACCUMULATE TO WEEKLY IF POSTED =====
                    if wo_data['is_posted']:
                        machine_info['weekly_totals']['total_output_qty'] += daily_data['output_qty'][i]
                        machine_info['weekly_totals']['total_working_hours'] += daily_data['working_hours'][i]
                        machine_info['weekly_totals']['total_planned_production'] += daily_data['planned_production'][i]
                        machine_info['weekly_totals']['total_rejects'] += daily_data['rejects'][i]
                        machine_info['weekly_totals']['total_cutbacks'] += daily_data['cutbacks'][i]
                        machine_info['weekly_totals']['total_absorption_hours'] += daily_data['absorption_hours'][i]
                        machine_info['weekly_totals']['total_wait_material'] += daily_data['wait_material'][i]
                        machine_info['weekly_totals']['total_meetings'] += daily_data['meetings'][i]
                        machine_info['weekly_totals']['total_breakdown'] += daily_data['breakdown'][i]
                        machine_info['weekly_totals']['total_change_over'] += daily_data['change_over'][i]
                        machine_info['weekly_totals']['total_operating_hours'] += daily_data['operating_hours'][i]
                        machine_info['weekly_totals']['total_non_recorded_time'] += daily_data['non_recorded_time'][i]
                        
                        # Update summary data
                        summary_data['daily_data'][date_index]['working_hours'] += daily_data['working_hours'][i]
                        summary_data['daily_data'][date_index]['planned_production'] += daily_data['planned_production'][i]
                        summary_data['daily_data'][date_index]['output_qty'] += daily_data['output_qty'][i]
                        summary_data['daily_data'][date_index]['rejects'] += daily_data['rejects'][i]
                        summary_data['daily_data'][date_index]['cutbacks'] += daily_data['cutbacks'][i]
                        summary_data['daily_data'][date_index]['absorption_hours'] += daily_data['absorption_hours'][i]
                        summary_data['daily_data'][date_index]['wait_material'] += daily_data['wait_material'][i]
                        summary_data['daily_data'][date_index]['meetings'] += daily_data['meetings'][i]
                        summary_data['daily_data'][date_index]['breakdown'] += daily_data['breakdown'][i]
                        summary_data['daily_data'][date_index]['change_over'] += daily_data['change_over'][i]
                        summary_data['daily_data'][date_index]['operating_hours'] += daily_data['operating_hours'][i]
                        summary_data['daily_data'][date_index]['non_recorded_time'] += daily_data['non_recorded_time'][i]
                        
                        # Accumulate for averages
                        if daily_data['oee'][i] > 0:
                            total_oee_sum += daily_data['oee'][i]
                            total_oee_count += 1
                        
                        if daily_data['reject_rate'][i] >= 0:
                            total_reject_rate_sum += daily_data['reject_rate'][i]
                            total_reject_rate_count += 1
            
            # ===== ONLY ACCUMULATE BOOKED HOURS IF POSTED =====
            for header in headers_for_date:
                if header.is_posted:
                    shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                    if header.booked_hours and header.booked_hours.duration:
                        booked_hours_value = float(header.booked_hours.duration)
                        machine_info['weekly_totals']['total_booked_hours_header'] += booked_hours_value
                        summary_data['daily_data'][date_index]['booked_hours_header'] += booked_hours_value
            
            # Calculate daily totals
            daily_data['total_working_hours'] = sum(daily_data['working_hours'])
            daily_data['total_output_qty'] = sum(daily_data['output_qty'])
            
            machine_info['daily_data'].append(daily_data)
        
        # Calculate machine averages
        machine_info['weekly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['weekly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets and calculate variance/percentage
        weekly_totals = machine_info['weekly_totals']
        
        # Define targets
        weekly_totals['target_booked_hours_header'] = 105.0
        weekly_totals['target_working_hours'] = 105.0
        weekly_totals['target_output_qty'] = 85.0
        weekly_totals['target_oee'] = 85.0
        weekly_totals['target_reject_rate'] = 1.5
        weekly_totals['target_absorption_hours'] = 16762.20
        weekly_totals['target_wait_material'] = 1.7
        weekly_totals['target_meetings'] = 0.8
        weekly_totals['target_breakdown'] = 1.7
        weekly_totals['target_change_over'] = 4.2
        weekly_totals['target_operating_hours'] = 84.0
        weekly_totals['target_non_recorded_time'] = 8.4
        
        # Calculate variances and percentages
        weekly_totals['variance_booked_hours_header'] = round(weekly_totals['total_booked_hours_header'] - weekly_totals['target_booked_hours_header'], 1) if weekly_totals['total_booked_hours_header'] > 0 else None
        weekly_totals['variance_working_hours'] = round(weekly_totals['total_working_hours'] - weekly_totals['target_working_hours'], 1) if weekly_totals['total_working_hours'] > 0 else None
        weekly_totals['variance_output_qty'] = round(weekly_totals['total_output_qty'] - weekly_totals['target_output_qty'], 1) if weekly_totals['total_output_qty'] > 0 else None
        weekly_totals['variance_oee'] = round(weekly_totals['average_oee'] - weekly_totals['target_oee'], 1) if weekly_totals['average_oee'] > 0 else None
        weekly_totals['variance_reject_rate'] = round(weekly_totals['average_reject_rate'] - weekly_totals['target_reject_rate'], 1) if weekly_totals['average_reject_rate'] >= 0 else None
        weekly_totals['variance_absorption_hours'] = round(weekly_totals['total_absorption_hours'] - weekly_totals['target_absorption_hours'], 2) if weekly_totals['total_absorption_hours'] > 0 else None
        weekly_totals['variance_wait_material'] = round(weekly_totals['total_wait_material'] - weekly_totals['target_wait_material'], 1) if weekly_totals['total_wait_material'] > 0 else None
        weekly_totals['variance_meetings'] = round(weekly_totals['total_meetings'] - weekly_totals['target_meetings'], 1) if weekly_totals['total_meetings'] > 0 else None
        weekly_totals['variance_breakdown'] = round(weekly_totals['total_breakdown'] - weekly_totals['target_breakdown'], 1) if weekly_totals['total_breakdown'] > 0 else None
        weekly_totals['variance_change_over'] = round(weekly_totals['total_change_over'] - weekly_totals['target_change_over'], 1) if weekly_totals['total_change_over'] > 0 else None
        weekly_totals['variance_operating_hours'] = round(weekly_totals['total_operating_hours'] - weekly_totals['target_operating_hours'], 1) if weekly_totals['total_operating_hours'] > 0 else None
        weekly_totals['variance_non_recorded_time'] = round(weekly_totals['total_non_recorded_time'] - weekly_totals['target_non_recorded_time'], 1) if weekly_totals['total_non_recorded_time'] > 0 else None
        
        weekly_totals['percent_booked_hours_header'] = round((weekly_totals['total_booked_hours_header'] / weekly_totals['target_booked_hours_header']) * 100, 1) if weekly_totals['total_booked_hours_header'] > 0 and weekly_totals['target_booked_hours_header'] > 0 else None
        weekly_totals['percent_working_hours'] = round((weekly_totals['total_working_hours'] / weekly_totals['target_working_hours']) * 100, 1) if weekly_totals['total_working_hours'] > 0 and weekly_totals['target_working_hours'] > 0 else None
        weekly_totals['percent_output_qty'] = round((weekly_totals['total_output_qty'] / weekly_totals['target_output_qty']) * 100, 1) if weekly_totals['total_output_qty'] > 0 and weekly_totals['target_output_qty'] > 0 else None
        weekly_totals['percent_oee'] = round((weekly_totals['average_oee'] / weekly_totals['target_oee']) * 100, 1) if weekly_totals['average_oee'] > 0 and weekly_totals['target_oee'] > 0 else None
        weekly_totals['percent_absorption_hours'] = round((weekly_totals['total_absorption_hours'] / weekly_totals['target_absorption_hours']) * 100, 1) if weekly_totals['total_absorption_hours'] > 0 and weekly_totals['target_absorption_hours'] > 0 else None
        weekly_totals['percent_wait_material'] = round((weekly_totals['total_wait_material'] / weekly_totals['target_wait_material']) * 100, 1) if weekly_totals['total_wait_material'] > 0 and weekly_totals['target_wait_material'] > 0 else None
        weekly_totals['percent_meetings'] = round((weekly_totals['total_meetings'] / weekly_totals['target_meetings']) * 100, 1) if weekly_totals['total_meetings'] > 0 and weekly_totals['target_meetings'] > 0 else None
        weekly_totals['percent_breakdown'] = round((weekly_totals['total_breakdown'] / weekly_totals['target_breakdown']) * 100, 1) if weekly_totals['total_breakdown'] > 0 and weekly_totals['target_breakdown'] > 0 else None
        weekly_totals['percent_change_over'] = round((weekly_totals['total_change_over'] / weekly_totals['target_change_over']) * 100, 1) if weekly_totals['total_change_over'] > 0 and weekly_totals['target_change_over'] > 0 else None
        weekly_totals['percent_operating_hours'] = round((weekly_totals['total_operating_hours'] / weekly_totals['target_operating_hours']) * 100, 1) if weekly_totals['total_operating_hours'] > 0 and weekly_totals['target_operating_hours'] > 0 else None
        weekly_totals['percent_non_recorded_time'] = round((weekly_totals['total_non_recorded_time'] / weekly_totals['target_non_recorded_time']) * 100, 1) if weekly_totals['total_non_recorded_time'] > 0 and weekly_totals['target_non_recorded_time'] > 0 else None
        
        machine_data.append(machine_info)
    
    # Step 4: Calculate summary totals and averages (ONLY FROM POSTED DATA)
    total_oee_values = []
    total_reject_rates = []
    
    for daily_summary in summary_data['daily_data']:
        if daily_summary['booked_hours_header'] > 0:
            daily_oee_values = []
            daily_reject_total = 0
            daily_cutback_total = 0
            daily_output_total = 0
            
            for machine_info in machine_data:
                for daily_data in machine_info['daily_data']:
                    if daily_data['date'] == daily_summary['date']:
                        # Only count posted data
                        for idx, oee_val in enumerate(daily_data['oee']):
                            if oee_val > 0 and daily_data['is_posted'][idx]:
                                daily_oee_values.append(oee_val)
                        
                        # Only count posted data for reject rate
                        for idx in range(len(daily_data['rejects'])):
                            if daily_data['is_posted'][idx]:
                                daily_reject_total += daily_data['rejects'][idx]
                                daily_cutback_total += daily_data['cutbacks'][idx]
                                daily_output_total += daily_data['output_qty'][idx]
            
            daily_summary['oee'] = round(sum(daily_oee_values) / len(daily_oee_values), 2) if daily_oee_values else 0
            
            total_production = daily_output_total + daily_reject_total + daily_cutback_total
            if total_production > 0:
                daily_summary['reject_rate'] = round(((daily_reject_total + daily_cutback_total) / total_production * 100), 2)
            else:
                daily_summary['reject_rate'] = 0
            
            if daily_summary['oee'] > 0:
                total_oee_values.append(daily_summary['oee'])
            if daily_summary['reject_rate'] >= 0:
                total_reject_rates.append(daily_summary['reject_rate'])
    
    # Calculate weekly summary totals
    summary_data['weekly_totals']['total_booked_hours_header'] = sum([d['booked_hours_header'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_working_hours'] = sum([d['working_hours'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_planned_production'] = sum([d['planned_production'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_output_qty'] = sum([d['output_qty'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_rejects'] = sum([d['rejects'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_cutbacks'] = sum([d['cutbacks'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_absorption_hours'] = sum([d['absorption_hours'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_wait_material'] = sum([d['wait_material'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_meetings'] = sum([d['meetings'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_breakdown'] = sum([d['breakdown'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_change_over'] = sum([d['change_over'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_operating_hours'] = sum([d['operating_hours'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_non_recorded_time'] = sum([d['non_recorded_time'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['average_oee'] = round(sum(total_oee_values) / len(total_oee_values), 2) if total_oee_values else 0
    summary_data['weekly_totals']['average_reject_rate'] = round(sum(total_reject_rates) / len(total_reject_rates), 2) if total_reject_rates else 0
    
    # Add summary targets
    summary_data['weekly_totals']['target_booked_hours_header'] = 315.0
    summary_data['weekly_totals']['target_working_hours'] = 315.0
    summary_data['weekly_totals']['target_output_qty'] = 255.0
    summary_data['weekly_totals']['target_oee'] = 85.0
    summary_data['weekly_totals']['target_reject_rate'] = 1.5
    summary_data['weekly_totals']['target_absorption_hours'] = 50286.60
    summary_data['weekly_totals']['target_wait_material'] = 5.1
    summary_data['weekly_totals']['target_meetings'] = 2.4
    summary_data['weekly_totals']['target_breakdown'] = 5.1
    summary_data['weekly_totals']['target_change_over'] = 12.6
    summary_data['weekly_totals']['target_operating_hours'] = 252.0
    summary_data['weekly_totals']['target_non_recorded_time'] = 25.2
    
    summary_totals = summary_data['weekly_totals']
    summary_totals['variance_booked_hours_header'] = round(summary_totals['total_booked_hours_header'] - summary_totals['target_booked_hours_header'], 1) if summary_totals['total_booked_hours_header'] > 0 else None
    summary_totals['variance_working_hours'] = round(summary_totals['total_working_hours'] - summary_totals['target_working_hours'], 1) if summary_totals['total_working_hours'] > 0 else None
    summary_totals['variance_output_qty'] = round(summary_totals['total_output_qty'] - summary_totals['target_output_qty'], 1) if summary_totals['total_output_qty'] > 0 else None
    summary_totals['variance_oee'] = round(summary_totals['average_oee'] - summary_totals['target_oee'], 1) if summary_totals['average_oee'] > 0 else None
    summary_totals['variance_reject_rate'] = round(summary_totals['average_reject_rate'] - summary_totals['target_reject_rate'], 1) if summary_totals['average_reject_rate'] >= 0 else None
    summary_totals['variance_absorption_hours'] = round(summary_totals['total_absorption_hours'] - summary_totals['target_absorption_hours'], 2) if summary_totals['total_absorption_hours'] > 0 else None
    summary_totals['variance_wait_material'] = round(summary_totals['total_wait_material'] - summary_totals['target_wait_material'], 1) if summary_totals['total_wait_material'] > 0 else None
    summary_totals['variance_meetings'] = round(summary_totals['total_meetings'] - summary_totals['target_meetings'], 1) if summary_totals['total_meetings'] > 0 else None
    summary_totals['variance_breakdown'] = round(summary_totals['total_breakdown'] - summary_totals['target_breakdown'], 1) if summary_totals['total_breakdown'] > 0 else None
    summary_totals['variance_change_over'] = round(summary_totals['total_change_over'] - summary_totals['target_change_over'], 1) if summary_totals['total_change_over'] > 0 else None
    summary_totals['variance_operating_hours'] = round(summary_totals['total_operating_hours'] - summary_totals['target_operating_hours'], 1) if summary_totals['total_operating_hours'] > 0 else None
    summary_totals['variance_non_recorded_time'] = round(summary_totals['total_non_recorded_time'] - summary_totals['target_non_recorded_time'], 1) if summary_totals['total_non_recorded_time'] > 0 else None
    
    summary_totals['percent_booked_hours_header'] = round((summary_totals['total_booked_hours_header'] / summary_totals['target_booked_hours_header']) * 100, 1) if summary_totals['total_booked_hours_header'] > 0 and summary_totals['target_booked_hours_header'] > 0 else None
    summary_totals['percent_working_hours'] = round((summary_totals['total_working_hours'] / summary_totals['target_working_hours']) * 100, 1) if summary_totals['total_working_hours'] > 0 and summary_totals['target_working_hours'] > 0 else None
    summary_totals['percent_output_qty'] = round((summary_totals['total_output_qty'] / summary_totals['target_output_qty']) * 100, 1) if summary_totals['total_output_qty'] > 0 and summary_totals['target_output_qty'] > 0 else None
    summary_totals['percent_oee'] = round((summary_totals['average_oee'] / summary_totals['target_oee']) * 100, 1) if summary_totals['average_oee'] > 0 and summary_totals['target_oee'] > 0 else None
    summary_totals['percent_absorption_hours'] = round((summary_totals['total_absorption_hours'] / summary_totals['target_absorption_hours']) * 100, 1) if summary_totals['total_absorption_hours'] > 0 and summary_totals['target_absorption_hours'] > 0 else None
    summary_totals['percent_wait_material'] = round((summary_totals['total_wait_material'] / summary_totals['target_wait_material']) * 100, 1) if summary_totals['total_wait_material'] > 0 and summary_totals['target_wait_material'] > 0 else None
    summary_totals['percent_meetings'] = round((summary_totals['total_meetings'] / summary_totals['target_meetings']) * 100, 1) if summary_totals['total_meetings'] > 0 and summary_totals['target_meetings'] > 0 else None
    summary_totals['percent_breakdown'] = round((summary_totals['total_breakdown'] / summary_totals['target_breakdown']) * 100, 1) if summary_totals['total_breakdown'] > 0 and summary_totals['target_breakdown'] > 0 else None
    summary_totals['percent_change_over'] = round((summary_totals['total_change_over'] / summary_totals['target_change_over']) * 100, 1) if summary_totals['total_change_over'] > 0 and summary_totals['target_change_over'] > 0 else None
    summary_totals['percent_operating_hours'] = round((summary_totals['total_operating_hours'] / summary_totals['target_operating_hours']) * 100, 1) if summary_totals['total_operating_hours'] > 0 and summary_totals['target_operating_hours'] > 0 else None
    summary_totals['percent_non_recorded_time'] = round((summary_totals['total_non_recorded_time'] / summary_totals['target_non_recorded_time']) * 100, 1) if summary_totals['total_non_recorded_time'] > 0 and summary_totals['target_non_recorded_time'] > 0 else None
    
    # Create week days labels
    week_days_labels = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    
    # Prepare context
    context = {
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        'week_number': week_number,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'week_days': week_days_labels,
        'columns_per_day': columns_per_day,
        'active_menu': 'thread_report_oee'
    }
    
    return render(request, 'thread/report_oee.html', context)

def joborder_tracking(request, bjo_id):
    try:
        bjo_header = JobHeader.objects.get(id=bjo_id)
    except JobHeader.DoesNotExist:
        messages.error(request, 'Job Order tidak ditemukan.')
        return redirect('joborder_list')
    
    joint_tracking = []
    protector_tracking = []
    box_completed = 0
    pin_completed = 0
    fs_completed = 0
    fcbs_completed = 0
    fcps_completed = 0
    
    # ✅ Flag untuk cek ketersediaan data
    has_box_weld = False
    has_pin_weld = False
    has_fs_weld = False
    has_fcbs_weld = False
    has_fcps_weld = False
    
    info_tag_name = bjo_header.info.name.upper() if bjo_header.info else ''
    process_name = bjo_header.process_type.name.upper() if bjo_header.process_type else ''
    
    is_bxb = 'B X B' in info_tag_name or 'BXB' in info_tag_name
    is_pxp = 'P X P' in info_tag_name or 'PXP' in info_tag_name
    is_weld = 'WELD' in process_name
    
    # ===== HELPER FUNCTION: GET ALL STAGES WITH STATUS =====
    def get_weld_stages(bjo, joint_num, side):
        """
        Ambil SEMUA stages welding untuk joint tertentu (uncompleted, completed, ncr, rework)
        Returns list of dict dengan info lengkap per stage
        """
        all_details = WeldDetail.objects.filter(
            bjo=bjo,
            joint_number=joint_num,
            pin_or_box=side
        ).select_related('Reff__machine', 'Reff__operator').order_by('created_at')
        
        stages = []
        for idx, detail in enumerate(all_details, start=1):
            # Cek status NCR
            has_ncr = WeldNcr.objects.filter(serial=detail).exists()
            
            # Cek status dari comment
            comment = detail.comment or ''
            is_reworked = 'REWORKED' in comment.upper()
            is_uncompleted_marker = 'UNCOMPLETED' in comment.upper()
            
            # Tentukan status stage
            if is_reworked:
                status = 'REWORK'
                status_class = 'badge-danger'
            elif is_uncompleted_marker or detail.is_uncompleted:
                status = 'UNCOMPLETED'
                status_class = 'badge-warning'
            elif has_ncr:
                status = 'NCR'
                status_class = 'badge-info'
            else:
                status = 'COMPLETED'
                status_class = 'badge-success'
            
            duration = calculate_time_duration(detail.start_time, detail.stop_time)
            
            stage_data = {
                'stage_number': idx,
                'date': detail.Reff.date if detail.Reff else None,
                'operator': detail.Reff.operator if detail.Reff else None,
                'machine': detail.Reff.machine if detail.Reff else None,
                'duration': duration,
                'output': detail.output,
                'status': status,
                'status_class': status_class,
                'comment': detail.comment,
                'start_time': detail.start_time,
                'stop_time': detail.stop_time,
                'has_ncr': has_ncr,
                'is_uncompleted': detail.is_uncompleted,
            }
            
            stages.append(stage_data)
        
        return stages
    
    def get_thread_stages(bjo, joint_num, side):
        """
        Ambil SEMUA stages threading untuk joint tertentu
        """
        all_details = ThreadDetail.objects.filter(
            bjo=bjo,
            joint_number=joint_num,
            pin_or_box=side
        ).select_related('Reff__machine', 'Reff__operator').order_by('created_at')
        
        stages = []
        for idx, detail in enumerate(all_details, start=1):
            # Cek status NCR
            has_ncr = ThreadNcr.objects.filter(serial=detail).exists()
            
            # Cek status dari comment
            comment = detail.comment or ''
            is_reworked = 'REWORKED' in comment.upper()
            is_uncompleted_marker = 'UNCOMPLETED' in comment.upper()
            
            # Tentukan status stage
            if is_reworked:
                status = 'REWORK'
                status_class = 'badge-danger'
            elif is_uncompleted_marker or detail.is_uncompleted:
                status = 'UNCOMPLETED'
                status_class = 'badge-warning'
            elif has_ncr:
                status = 'NCR'
                status_class = 'badge-info'
            else:
                status = 'COMPLETED'
                status_class = 'badge-success'
            
            duration = calculate_time_duration(detail.start_time, detail.stop_time)
            
            stage_data = {
                'stage_number': idx,
                'date': detail.Reff.date if detail.Reff else None,
                'operator': detail.Reff.operator if detail.Reff else None,
                'machine': detail.Reff.machine if detail.Reff else None,
                'duration': duration,
                'output': detail.output,
                'status': status,
                'status_class': status_class,
                'comment': detail.comment,
                'start_time': detail.start_time,
                'stop_time': detail.stop_time,
                'has_ncr': has_ncr,
                'is_uncompleted': detail.is_uncompleted,
            }
            
            stages.append(stage_data)
        
        return stages
    
    # ===== MAIN LOGIC =====
    if bjo_header.bjo_for == 'PIPE':
        serial_numbers = SerialNumber.objects.filter(bjo=bjo_header).order_by('joint_number')
        
        if is_weld:
            # ✅ WELDING: Ambil semua stages untuk setiap sisi
            for serial in serial_numbers:
                box_stages = get_weld_stages(bjo_header, serial.joint_number, 'BOX')
                pin_stages = get_weld_stages(bjo_header, serial.joint_number, 'PIN')
                fs_stages = get_weld_stages(bjo_header, serial.joint_number, 'FLOAT SHOE')
                fcbs_stages = get_weld_stages(bjo_header, serial.joint_number, 'FLOAT COLAR BOX SIDE')
                fcps_stages = get_weld_stages(bjo_header, serial.joint_number, 'FLOAT COLAR PIN SIDE')
                
                # Count completed stages
                box_completed += len([s for s in box_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                pin_completed += len([s for s in pin_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                fs_completed += len([s for s in fs_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                fcbs_completed += len([s for s in fcbs_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                fcps_completed += len([s for s in fcps_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                
                # Set flags
                if box_stages:
                    has_box_weld = True
                if pin_stages:
                    has_pin_weld = True
                if fs_stages:
                    has_fs_weld = True
                if fcbs_stages:
                    has_fcbs_weld = True
                if fcps_stages:
                    has_fcps_weld = True
                
                joint_data = {
                    'joint_number': serial.joint_number,
                    'box_stages': box_stages,
                    'pin_stages': pin_stages,
                    'fs_stages': fs_stages,
                    'fcbs_stages': fcbs_stages,
                    'fcps_stages': fcps_stages,
                }
                
                joint_tracking.append(joint_data)
        
        else:
            # ✅ THREADING
            if is_pxp:
                # P X P: Bisa PIN 2x atau kombinasi
                for serial in serial_numbers:
                    all_stages = get_thread_stages(bjo_header, serial.joint_number, 'PIN')
                    all_stages += get_thread_stages(bjo_header, serial.joint_number, 'BOX')
                    
                    # Sort by created_at
                    all_stages.sort(key=lambda x: (x['date'] or '', x['start_time'] or ''))
                    
                    pin_completed += len([s for s in all_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'all_stages': all_stages,
                    }
                    
                    joint_tracking.append(joint_data)
                    
            elif is_bxb:
                # B X B: Bisa BOX 2x atau kombinasi
                for serial in serial_numbers:
                    all_stages = get_thread_stages(bjo_header, serial.joint_number, 'BOX')
                    all_stages += get_thread_stages(bjo_header, serial.joint_number, 'PIN')
                    
                    # Sort by created_at
                    all_stages.sort(key=lambda x: (x['date'] or '', x['start_time'] or ''))
                    
                    box_completed += len([s for s in all_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'all_stages': all_stages,
                    }
                    
                    joint_tracking.append(joint_data)
            
            else:
                # THREADING BIASA: BOX + PIN terpisah
                for serial in serial_numbers:
                    box_stages = get_thread_stages(bjo_header, serial.joint_number, 'BOX')
                    pin_stages = get_thread_stages(bjo_header, serial.joint_number, 'PIN')
                    
                    box_completed += len([s for s in box_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                    pin_completed += len([s for s in pin_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'box_stages': box_stages,
                        'pin_stages': pin_stages,
                    }
                    
                    joint_tracking.append(joint_data)
            
    elif bjo_header.bjo_for == 'BOX PROTECTOR':
        box_protectors = BoxProtector.objects.filter(bjo=bjo_header).order_by('serial_number')
        
        for protector in box_protectors:
            box_stages = get_thread_stages(bjo_header, protector.serial_number, 'BOX')
            box_completed += len([s for s in box_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
            
            protector_data = {
                'protector_number': protector.serial_number,
                'box_stages': box_stages,
            }
            
            protector_tracking.append(protector_data)
            
    elif bjo_header.bjo_for == 'PIN PROTECTOR':
        pin_protectors = PinProtector.objects.filter(bjo=bjo_header).order_by('serial_number')
        
        for protector in pin_protectors:
            pin_stages = get_thread_stages(bjo_header, protector.serial_number, 'PIN')
            pin_completed += len([s for s in pin_stages if s['status'] == 'COMPLETED' or s['status'] == 'REWORK'])
            
            protector_data = {
                'protector_number': protector.serial_number,
                'pin_stages': pin_stages,
            }
            
            protector_tracking.append(protector_data)
    
    context = {
        'bjo_header': bjo_header,
        'joint_tracking': joint_tracking,
        'protector_tracking': protector_tracking,
        'box_completed': box_completed,
        'pin_completed': pin_completed,
        'fs_completed': fs_completed,
        'fcbs_completed': fcbs_completed,
        'fcps_completed': fcps_completed,
        'is_pxp': is_pxp,
        'is_bxb': is_bxb,
        'is_weld': is_weld,
        'has_box_weld': has_box_weld,
        'has_pin_weld': has_pin_weld,
        'has_fs_weld': has_fs_weld,
        'has_fcbs_weld': has_fcbs_weld,
        'has_fcps_weld': has_fcps_weld,
        'active_menu': 'joborder_list',
    }
    
    return render(request, 'joborder/tracking_base.html', context)

def joborder_print_report(request, bjo_id, report_type=None):
    """
    Unified report function untuk AB (Threading) dan BB (Weld Final)
    report_type: 'AB' untuk threading report, 'BB' untuk weld final report
    Jika None, akan auto-detect dari type_order
    """
    try:
        bjo_header = JobHeader.objects.get(id=bjo_id)
    except JobHeader.DoesNotExist:
        messages.error(request, 'Job Order tidak ditemukan.')
        return redirect('joborder_list')
    
    joint_tracking = []
    
    # Auto-detect report_type dari type_order jika tidak dispesifikasi
    if report_type is None:
        if bjo_header.type_order:
            if 'BB' in bjo_header.type_order:
                report_type = 'BB'
            elif 'AB' in bjo_header.type_order:
                report_type = 'AB'
            else:
                report_type = 'AB'  # default
        else:
            report_type = 'AB'  # default
    
    # Ekstraksi form_type dari type_order
    if bjo_header.type_order:
        if f'{report_type}-1.1' in bjo_header.type_order:
            form_type = f'{report_type}-1.1'
        elif f'{report_type}-1' in bjo_header.type_order:
            form_type = f'{report_type}-1'
        elif f'{report_type}-2.3' in bjo_header.type_order:
            form_type = f'{report_type}-2.3'
        elif f'{report_type}-2.1' in bjo_header.type_order:
            form_type = f'{report_type}-2.1'
        elif f'{report_type}-2.2' in bjo_header.type_order:
            form_type = f'{report_type}-2.2'
        elif f'{report_type}-2' in bjo_header.type_order:
            form_type = f'{report_type}-2'
        elif f'{report_type}-3' in bjo_header.type_order:
            form_type = f'{report_type}-3'
        else:
            if report_type == 'AB':
                form_type = 'AB-1' if bjo_header.bjo_for in ['BOX PROTECTOR', 'PIN PROTECTOR'] else 'AB-3'
            else:  # BB
                form_type = 'BB-1'
    else:
        if report_type == 'AB':
            form_type = 'AB-1' if bjo_header.bjo_for in ['BOX PROTECTOR', 'PIN PROTECTOR'] else 'AB-3'
        else:  # BB
            form_type = 'BB-1'
    
    # Cek Info Tag
    info_tag_name = bjo_header.info.name.upper() if bjo_header.info else ''
    is_bxb = 'B X B' in info_tag_name or 'BXB' in info_tag_name
    is_pxp = 'P X P' in info_tag_name or 'PXP' in info_tag_name
    
    # ✅ FIXED: Helper function untuk menentukan Accept/Reject
    def get_accept_reject_status(thread_detail, joint_number):
        if not thread_detail or not thread_detail.Reff:
            return None
        
        reason_stops = TreadReasonStop.objects.filter(
            Reff=thread_detail.Reff,
            bjo=thread_detail.bjo
        )
        
        joint_number_str = str(joint_number)
        
        for reason_stop in reason_stops:
            if reason_stop.reject and reason_stop.reject > 0:
                if hasattr(reason_stop, 'rejected_joints') and reason_stop.rejected_joints:
                    rejected_joints_str = str(reason_stop.rejected_joints)
                    rejected_joints_list = [j.strip() for j in rejected_joints_str.split(',')]
                    if joint_number_str in rejected_joints_list:
                        return "Reject"
        
        return "Accept"

    # ✅ FIXED: Helper function untuk ambil protector dari multiple PipeDetail records
    def get_pipe_protectors(serial):
        """
        Ambil box_protector, pin_protector, dan tally dari semua PipeDetail
        untuk joint ini. Menggabungkan data yang mungkin tersimpan di
        header/sesi berbeda.
        """
        pipe_details = PipeDetail.objects.filter(joint_number=serial)
        
        box_protector = None
        pin_protector = None
        tally = None
        
        for pd in pipe_details:
            if pd.box_protector and not box_protector:
                box_protector = pd.box_protector.protector_serial
            if pd.pin_protector and not pin_protector:
                pin_protector = pd.pin_protector.protector_serial
            if pd.tally and not tally:
                tally = pd.tally
        
        return box_protector, pin_protector, tally
    
    # ✅ BAGIAN PERBAIKAN: AB-1 untuk PROTECTOR - WITH COMMENTS
    if bjo_header.bjo_for in ['BOX PROTECTOR', 'PIN PROTECTOR'] and report_type == 'AB':
        if bjo_header.bjo_for == 'BOX PROTECTOR':
            protectors = BoxProtector.objects.filter(bjo=bjo_header).order_by('serial_number')
            pin_or_box = 'BOX'
        else:  # PIN PROTECTOR
            protectors = PinProtector.objects.filter(bjo=bjo_header).order_by('serial_number')
            pin_or_box = 'PIN'
        
        for protector in protectors:
            cutting = None
            
            cutting = cut_detail.objects.filter(
                reff__bjo_protector=bjo_header,
                protector_number=protector.serial_number
            ).select_related('reff', 'reff__operator', 'reff__shift').first()
            
            if not cutting:
                cutting = cut_detail.objects.filter(
                    protector_number=protector.serial_number
                ).select_related('reff', 'reff__operator', 'reff__shift').first()
            
            if not cutting:
                cutting = cut_detail.objects.filter(
                    protector_number__iexact=protector.serial_number.strip()
                ).select_related('reff', 'reff__operator', 'reff__shift').first()
            
            if not cutting:
                all_cuts = cut_detail.objects.select_related('reff', 'reff__operator', 'reff__shift').all()
                protector_clean = protector.serial_number.replace(" ", "").upper()
                for cut in all_cuts:
                    if cut.protector_number:
                        cut_clean = cut.protector_number.replace(" ", "").upper()
                        if cut_clean == protector_clean:
                            cutting = cut
                            break
            
            thread = None
            
            if cutting and cutting.joint_number:
                thread = ThreadDetail.objects.filter(
                    bjo=bjo_header,
                    joint_number=cutting.joint_number,
                    pin_or_box=pin_or_box,
                    is_uncompleted=False
                ).select_related('Reff', 'Reff__operator').first()
            
            if not thread:
                thread = ThreadDetail.objects.filter(
                    bjo=bjo_header,
                    joint_number=protector.serial_number,
                    pin_or_box=pin_or_box,
                    is_uncompleted=False
                ).select_related('Reff', 'Reff__operator').first()
            
            if not thread:
                protector_clean = protector.serial_number.replace(" ", "")
                thread = ThreadDetail.objects.filter(
                    bjo=bjo_header,
                    joint_number__iexact=protector_clean,
                    pin_or_box=pin_or_box,
                    is_uncompleted=False
                ).select_related('Reff', 'Reff__operator').first()
            
            if not thread:
                all_threads = ThreadDetail.objects.filter(
                    bjo=bjo_header,
                    pin_or_box=pin_or_box,
                    is_uncompleted=False
                ).select_related('Reff', 'Reff__operator')
                protector_clean = protector.serial_number.replace(" ", "").upper()
                for th in all_threads:
                    if th.joint_number:
                        thread_joint_clean = th.joint_number.replace(" ", "").upper()
                        if thread_joint_clean == protector_clean:
                            thread = th
                            break
            
            thread_comment = None
            if thread and thread.Reff:
                if thread.Reff.is_posted and thread.Reff.comment:
                    thread_comment = thread.Reff.comment
            
            joint_data = {
                'joint_number': cutting.joint_number if cutting else None,
                'protector_no': protector.serial_number,
                'cutting_date': cutting.reff.created_at if cutting and cutting.reff else None,
                'cutting_operator': cutting.reff.operator.name if cutting and cutting.reff and cutting.reff.operator else None,
                'threading_date': thread.Reff.date if thread and thread.Reff else None,
                'threading_operator': thread.Reff.operator if thread and thread.Reff else None,
                'comments': thread_comment,
            }
            
            joint_tracking.append(joint_data)
    
    elif bjo_header.bjo_for == 'PIPE':
        serial_numbers = SerialNumber.objects.filter(bjo=bjo_header).order_by('joint_number')
        
        if is_pxp:
            # P X P: 2x threading per joint (PIN)
            for serial in serial_numbers:
                if report_type == 'AB':
                    thread_1st = None
                    thread_2nd = None
                    connector = None
                    conn_number = None
                    protector_1st = None
                    protector_2nd = None
                    comment_1st = None
                    comment_2nd = None
                    
                    connector = Connector.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number
                    ).first()
                    conn_number = connector.conn_number if connector else None
                    
                    all_threads = ThreadDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).select_related('Reff').order_by('created_at')
                    
                    thread_1st = all_threads[0] if all_threads.count() > 0 else None
                    thread_2nd = all_threads[1] if all_threads.count() > 1 else None
                    
                    # ✅ FIXED: Gunakan helper untuk ambil protector dari semua records
                    _, pin_protector_serial, tally = get_pipe_protectors(serial)
                    
                    if thread_1st:
                        protector_1st = pin_protector_serial
                    if thread_2nd:
                        protector_2nd = pin_protector_serial
                    
                    pin_acc_reject_1st = get_accept_reject_status(thread_1st, serial.joint_number) if form_type == 'AB-2' and thread_1st else None
                    pin_acc_reject_2nd = get_accept_reject_status(thread_2nd, serial.joint_number) if form_type == 'AB-2' and thread_2nd else None
                    
                    if thread_1st and thread_1st.Reff:
                        if thread_1st.Reff.is_posted and thread_1st.Reff.comment:
                            comment_1st = thread_1st.Reff.comment
                    if thread_2nd and thread_2nd.Reff:
                        if thread_2nd.Reff.is_posted and thread_2nd.Reff.comment:
                            comment_2nd = thread_2nd.Reff.comment
                    
                    comments_parts = []
                    if comment_1st:
                        comments_parts.append(f"1st: {comment_1st}")
                    if comment_2nd:
                        comments_parts.append(f"2nd: {comment_2nd}")
                    combined_comment = " | ".join(comments_parts) if comments_parts else None
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'conn_number': conn_number,
                        'pin_thread_date_1st': thread_1st.Reff.date if thread_1st and thread_1st.Reff else None,
                        'pin_thread_operator_1st': thread_1st.Reff.operator if thread_1st and thread_1st.Reff else None,
                        'pin_acc_reject_1st': pin_acc_reject_1st,
                        'pin_thread_date_2nd': thread_2nd.Reff.date if thread_2nd and thread_2nd.Reff else None,
                        'pin_thread_operator_2nd': thread_2nd.Reff.operator if thread_2nd and thread_2nd.Reff else None,
                        'pin_acc_reject_2nd': pin_acc_reject_2nd,
                        'pin_protector_1st': protector_1st,
                        'pin_protector_2nd': protector_2nd,
                        'tally': tally,
                        'comments': combined_comment,
                    }
                    
                else:  # BB REPORT: WELD FINAL
                    pin_weld = None
                    box_weld = None
                    weld_final = None
                    operator_name = None
                    pin_conn = None
                    box_conn = None
                    
                    pin_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    box_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    weld_final = weldfinal_detail.objects.filter(
                        joint_number=serial,
                        weldfinal_header__bjo=bjo_header
                    ).select_related('weldfinal_header').first()
                    
                    operator_name = weld_final.weldfinal_header.operator_name if weld_final and weld_final.weldfinal_header else None
                    pin_conn = pin_weld.conn_number if pin_weld else None
                    box_conn = box_weld.conn_number if box_weld else None
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'pin_date': pin_weld.Reff.date if pin_weld and pin_weld.Reff else None,
                        'pin_welder': pin_weld.Reff.operator if pin_weld and pin_weld.Reff else None,
                        'pin_side': pin_conn,
                        'box_date': box_weld.Reff.date if box_weld and box_weld.Reff else None,
                        'box_welder': box_weld.Reff.operator if box_weld and box_weld.Reff else None,
                        'box_side': box_conn,
                        'box_forging': box_conn,
                        'pin_forging': pin_conn,
                        'box_end': box_conn,
                        'pin_end': pin_conn,
                        'bevel_pin': weld_final.bevel_pin if weld_final else False,
                        'bevel_pin_operator': operator_name if weld_final and weld_final.bevel_pin else None,
                        'bevel_box': weld_final.bevel_box if weld_final else False,
                        'bevel_box_operator': operator_name if weld_final and weld_final.bevel_box else None,
                        'grind_pin': weld_final.grind_pin if weld_final else False,
                        'grind_pin_operator': operator_name if weld_final and weld_final.grind_pin else None,
                        'grind_box': weld_final.grind_box if weld_final else False,
                        'grind_box_operator': operator_name if weld_final and weld_final.grind_box else None,
                        'tally': weld_final.tally if weld_final and weld_final.tally else None,
                    }
                
                joint_tracking.append(joint_data)
                
        elif is_bxb:
            # B X B: 2x threading per joint (BOX)
            for serial in serial_numbers:
                if report_type == 'AB':
                    thread_1st = None
                    thread_2nd = None
                    connector = None
                    conn_number = None
                    protector_1st = None
                    protector_2nd = None
                    comment_1st = None
                    comment_2nd = None
                    
                    connector = Connector.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number
                    ).first()
                    conn_number = connector.conn_number if connector else None
                    
                    all_threads = ThreadDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).select_related('Reff').order_by('created_at')
                    
                    thread_1st = all_threads[0] if all_threads.count() > 0 else None
                    thread_2nd = all_threads[1] if all_threads.count() > 1 else None
                    
                    # ✅ FIXED: Gunakan helper untuk ambil protector dari semua records
                    box_protector_serial, _, tally = get_pipe_protectors(serial)
                    
                    if thread_1st:
                        protector_1st = box_protector_serial
                    if thread_2nd:
                        protector_2nd = box_protector_serial
                    
                    box_acc_reject_1st = get_accept_reject_status(thread_1st, serial.joint_number) if form_type == 'AB-2' and thread_1st else None
                    box_acc_reject_2nd = get_accept_reject_status(thread_2nd, serial.joint_number) if form_type == 'AB-2' and thread_2nd else None
                    
                    if thread_1st and thread_1st.Reff:
                        if thread_1st.Reff.is_posted and thread_1st.Reff.comment:
                            comment_1st = thread_1st.Reff.comment
                    if thread_2nd and thread_2nd.Reff:
                        if thread_2nd.Reff.is_posted and thread_2nd.Reff.comment:
                            comment_2nd = thread_2nd.Reff.comment
                    
                    comments_parts = []
                    if comment_1st:
                        comments_parts.append(f"1st: {comment_1st}")
                    if comment_2nd:
                        comments_parts.append(f"2nd: {comment_2nd}")
                    combined_comment = " | ".join(comments_parts) if comments_parts else None
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'conn_number': conn_number,
                        'box_thread_date_1st': thread_1st.Reff.date if thread_1st and thread_1st.Reff else None,
                        'box_thread_operator_1st': thread_1st.Reff.operator if thread_1st and thread_1st.Reff else None,
                        'box_acc_reject_1st': box_acc_reject_1st,
                        'box_thread_date_2nd': thread_2nd.Reff.date if thread_2nd and thread_2nd.Reff else None,
                        'box_thread_operator_2nd': thread_2nd.Reff.operator if thread_2nd and thread_2nd.Reff else None,
                        'box_acc_reject_2nd': box_acc_reject_2nd,
                        'box_protector_1st': protector_1st,
                        'box_protector_2nd': protector_2nd,
                        'tally': tally,
                        'comments': combined_comment,
                    }
                    
                else:  # BB REPORT: WELD FINAL
                    box_weld = None
                    pin_weld = None
                    weld_final = None
                    operator_name = None
                    box_conn = None
                    pin_conn = None
                    
                    box_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    pin_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    weld_final = weldfinal_detail.objects.filter(
                        joint_number=serial,
                        weldfinal_header__bjo=bjo_header
                    ).select_related('weldfinal_header').first()
                    
                    operator_name = weld_final.weldfinal_header.operator_name if weld_final and weld_final.weldfinal_header else None
                    box_conn = box_weld.conn_number if box_weld else None
                    pin_conn = pin_weld.conn_number if pin_weld else None
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'box_date': box_weld.Reff.date if box_weld and box_weld.Reff else None,
                        'box_welder': box_weld.Reff.operator if box_weld and box_weld.Reff else None,
                        'pin_date': pin_weld.Reff.date if pin_weld and pin_weld.Reff else None,
                        'pin_welder': pin_weld.Reff.operator if pin_weld and pin_weld.Reff else None,
                        'box_forging': box_conn,
                        'pin_forging': pin_conn,
                        'box_end': box_conn,
                        'pin_end': pin_conn,
                        'pin_side': pin_conn,
                        'box_side': box_conn,
                        'bevel_pin': weld_final.bevel_pin if weld_final else False,
                        'bevel_pin_operator': operator_name if weld_final and weld_final.bevel_pin else None,
                        'bevel_box': weld_final.bevel_box if weld_final else False,
                        'bevel_box_operator': operator_name if weld_final and weld_final.bevel_box else None,
                        'grind_pin': weld_final.grind_pin if weld_final else False,
                        'grind_pin_operator': operator_name if weld_final and weld_final.grind_pin else None,
                        'grind_box': weld_final.grind_box if weld_final else False,
                        'grind_box_operator': operator_name if weld_final and weld_final.grind_box else None,
                        'tally': weld_final.tally if weld_final and weld_final.tally else None,
                    }
                
                joint_tracking.append(joint_data)
                
        else:
            # NORMAL PIPE: BOX + PIN (1x masing-masing)
            for serial in serial_numbers:
                if report_type == 'AB':
                    box_thread = None
                    pin_thread = None
                    connector = None
                    conn_number = None
                    box_comment = None
                    pin_comment = None
                    
                    connector = Connector.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number
                    ).first()
                    conn_number = connector.conn_number if connector else None
                    
                    box_thread = ThreadDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    pin_thread = ThreadDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).select_related('Reff').first()
                    
                    # ✅ FIXED: Gunakan helper untuk ambil protector dari semua records
                    box_protector_serial, pin_protector_serial, tally = get_pipe_protectors(serial)
                    
                    box_acc_reject = get_accept_reject_status(box_thread, serial.joint_number) if form_type == 'AB-2' and box_thread else None
                    pin_acc_reject = get_accept_reject_status(pin_thread, serial.joint_number) if form_type == 'AB-2' and pin_thread else None
                    
                    if box_thread and box_thread.Reff:
                        if box_thread.Reff.is_posted and box_thread.Reff.comment:
                            box_comment = box_thread.Reff.comment
                    if pin_thread and pin_thread.Reff:
                        if pin_thread.Reff.is_posted and pin_thread.Reff.comment:
                            pin_comment = pin_thread.Reff.comment
                    
                    comments_parts = []
                    if box_comment:
                        comments_parts.append(f"Box: {box_comment}")
                    if pin_comment:
                        comments_parts.append(f"Pin: {pin_comment}")
                    combined_comment = " | ".join(comments_parts) if comments_parts else None
                    
                    joint_data = {
                        'joint_number': serial.joint_number,
                        'conn_number': conn_number,
                        'box_thread_date': box_thread.Reff.date if box_thread and box_thread.Reff else None,
                        'box_thread_operator': box_thread.Reff.operator if box_thread and box_thread.Reff else None,
                        'box_acc_reject': box_acc_reject,
                        'pin_thread_date': pin_thread.Reff.date if pin_thread and pin_thread.Reff else None,
                        'pin_thread_operator': pin_thread.Reff.operator if pin_thread and pin_thread.Reff else None,
                        'pin_acc_reject': pin_acc_reject,
                        'box_protector': box_protector_serial,
                        'pin_protector': pin_protector_serial,
                        'tally': tally,
                        'comments': combined_comment,
                    }
                    
                else:  # BB REPORT: WELD FINAL
                    box_weld = None
                    pin_weld = None
                    fcbs_weld = None
                    fcps_weld = None
                    weld_final = None
                    operator_name = None
                    box_conn = None
                    pin_conn = None
                    fcbs_conn = None
                    fcps_conn = None

                    box_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='BOX',
                        is_uncompleted=False
                    ).select_related('Reff').first()

                    pin_weld = WeldDetail.objects.filter(
                        bjo=bjo_header,
                        joint_number=serial.joint_number,
                        pin_or_box='PIN',
                        is_uncompleted=False
                    ).select_related('Reff').first()

                    if form_type == 'BB-2.3':
                        fcbs_weld = WeldDetail.objects.filter(
                            bjo=bjo_header,
                            joint_number=serial.joint_number,
                            pin_or_box='FLOAT COLAR BOX SIDE',
                            is_uncompleted=False
                        ).select_related('Reff').first()

                        fcps_weld = WeldDetail.objects.filter(
                            bjo=bjo_header,
                            joint_number=serial.joint_number,
                            pin_or_box='FLOAT COLAR PIN SIDE',
                            is_uncompleted=False
                        ).select_related('Reff').first()

                    # ✅ BB-1.1: Float Shoe query
                    float_shoe_weld = None
                    if form_type == 'BB-1.1':
                        float_shoe_weld = WeldDetail.objects.filter(
                            bjo=bjo_header,
                            joint_number=serial.joint_number,
                            pin_or_box='FLOAT SHOE',
                            is_uncompleted=False
                        ).select_related('Reff').first()

                    weld_final = weldfinal_detail.objects.filter(
                        joint_number=serial,
                        weldfinal_header__bjo=bjo_header
                    ).select_related('weldfinal_header').first()

                    operator_name = weld_final.weldfinal_header.operator_name if weld_final and weld_final.weldfinal_header else None
                    box_conn  = box_weld.conn_number  if box_weld  else None
                    pin_conn  = pin_weld.conn_number  if pin_weld  else None
                    fcbs_conn = fcbs_weld.conn_number if fcbs_weld else None
                    fcps_conn = fcps_weld.conn_number if fcps_weld else None
                    float_shoe_conn = float_shoe_weld.conn_number if float_shoe_weld else None

                    joint_data = {
                        'joint_number': serial.joint_number,
                        'box_date':    box_weld.Reff.date     if box_weld and box_weld.Reff else None,
                        'box_welder':  box_weld.Reff.operator if box_weld and box_weld.Reff else None,
                        'box_forging': box_conn,
                        'pin_date':    pin_weld.Reff.date     if pin_weld and pin_weld.Reff else None,
                        'pin_welder':  pin_weld.Reff.operator if pin_weld and pin_weld.Reff else None,
                        'pin_forging': pin_conn,
                        'fcbs_date':   fcbs_weld.Reff.date     if fcbs_weld and fcbs_weld.Reff else None,
                        'fcbs_welder': fcbs_weld.Reff.operator if fcbs_weld and fcbs_weld.Reff else None,
                        'box_side':    fcbs_conn,
                        'fcps_date':   fcps_weld.Reff.date     if fcps_weld and fcps_weld.Reff else None,
                        'fcps_welder': fcps_weld.Reff.operator if fcps_weld and fcps_weld.Reff else None,
                        'pin_side':    fcps_conn,
                        'box_end': box_conn,
                        'pin_end': pin_conn,
                        # ✅ BB-1.1: Float Shoe fields
                        'float_date':   float_shoe_weld.Reff.date     if float_shoe_weld and float_shoe_weld.Reff else None,
                        'float_welder': float_shoe_weld.Reff.operator if float_shoe_weld and float_shoe_weld.Reff else None,
                        'float_shoe':   float_shoe_conn,
                        'bevel_pin':          weld_final.bevel_pin  if weld_final else False,
                        'bevel_pin_operator': operator_name if weld_final and weld_final.bevel_pin  else None,
                        'bevel_box':          weld_final.bevel_box  if weld_final else False,
                        'bevel_box_operator': operator_name if weld_final and weld_final.bevel_box  else None,
                        'grind_pin':          weld_final.grind_pin  if weld_final else False,
                        'grind_pin_operator': operator_name if weld_final and weld_final.grind_pin  else None,
                        'grind_box':          weld_final.grind_box  if weld_final else False,
                        'grind_box_operator': operator_name if weld_final and weld_final.grind_box  else None,
                        'tally':              weld_final.tally if weld_final and weld_final.tally else None,
                    }
                    
                joint_tracking.append(joint_data)
                
    # ✅ PENTING: Bagian ini HARUS di level yang sama dengan if bjo_header.bjo_for
    current_date = datetime.now().strftime('%m/%d/%Y %I:%M %p')

    # BB-2.3 di badge tetap tampil sebagai BB-2
    # BB-1.1 di badge tetap tampil sebagai BB-1
    if form_type == 'BB-2.3':
        display_form_type = 'BB-2'
    elif form_type == 'BB-1.1':
        display_form_type = 'BB-1'
    else:
        display_form_type = form_type

    context = {
        'bjo_header': bjo_header,
        'joint_tracking': joint_tracking,
        'current_date': current_date,
        'form_type': display_form_type,
        'active_menu': 'joborder_list' if report_type == 'AB' else 'weldfinal_list',
    }

    # Template mapping based on report_type and form_type
    if report_type == 'AB':
        template_map = {
            'AB-1': 'joborder/report_xl100_ab1.html',
            'AB-2': 'joborder/report_xl100_ab2.html',
            'AB-3': 'joborder/report_xl100_ab3.html',
        }
        template = template_map.get(form_type, 'joborder/report_xl100_ab3.html')
    else:  # BB
        if form_type == 'BB-1.1':
            template = 'joborder/report_xl100_bb1_1.html'
        elif form_type == 'BB-1':
            template = 'joborder/report_xl100_bb1.html'
        elif form_type == 'BB-2' or form_type == 'BB-2.1':
            template = 'joborder/report_xl100_bb2_1.html'
        elif form_type == 'BB-2.2':
            template = 'joborder/report_xl100_bb2_2.html'
        elif form_type == 'BB-2.3':
            template = 'joborder/report_xl100_bb2_3.html'
        else:
            if is_bxb:
                template = 'joborder/report_xl100_bb2_1.html'
            elif is_pxp:
                template = 'joborder/report_xl100_bb2_2.html'
            else:
                template = 'joborder/report_xl100_bb1.html'

    return render(request, template, context)

@welding_report_access_required
def weld_report_oee(request):
    # Get date range from request or default to current week
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not start_date or not end_date:
        # Default to current week (Sunday to Saturday)
        today = datetime.now().date()
        
        # Calculate days since last Sunday
        # Sunday = 6, Monday = 0, Tuesday = 1, ..., Saturday = 5
        days_since_sunday = (today.weekday() + 1) % 7
        
        # Find the Sunday of current week
        start_date = today - timedelta(days=days_since_sunday)
        # End date is Saturday (6 days after Sunday)
        end_date = start_date + timedelta(days=6)
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        # Auto-adjust to Sunday-Saturday week if needed
        # Find the Sunday that contains or precedes the start_date
        days_since_sunday = (start_date.weekday() + 1) % 7
        adjusted_start = start_date - timedelta(days=days_since_sunday)
        adjusted_end = adjusted_start + timedelta(days=6)
        
        # Use adjusted dates if the original range doesn't span exactly 7 days
        if (end_date - start_date).days != 6:
            start_date = adjusted_start
            end_date = adjusted_end
    
    # Calculate week number
    week_number = start_date.isocalendar()[1] + 1
    
    # Get all machines that are welding type
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=welding_process)
    
    # Create date range (Sunday to Saturday)
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timedelta(days=1)
    
    # Ensure we have exactly 7 days
    assert len(date_range) == 7, "Week should contain exactly 7 days"
    
    # Get welding headers for the date range (INCLUDE NON-POSTED RECORDS)
    weld_headers = WeldHeader.objects.filter(
        date__range=[start_date, end_date]
    ).select_related('machine', 'operator', 'shift', 'booked_hours')
    
    # Step 1: Calculate maximum work orders per day (count work_order + shift combination)
    columns_per_day = {}
    
    for date in date_range:
        max_work_orders_for_date = 0
        
        # Check each machine for this date to find the maximum work orders
        for machine in machines:
            work_order_shift_combinations = []
            headers_for_machine_date = weld_headers.filter(machine=machine, date=date)
            
            for header in headers_for_machine_date:
                details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        # Create unique identifier: work_order + shift
                        work_order_shift_key = f"{detail.bjo.bjo}_{header.shift.name if header.shift else 'NO_SHIFT'}"
                        if work_order_shift_key not in work_order_shift_combinations:
                            work_order_shift_combinations.append(work_order_shift_key)
            
            # Update max for this date
            max_work_orders_for_date = max(max_work_orders_for_date, len(work_order_shift_combinations))
        
        # Store column count for this date (minimum 1)
        columns_per_day[date] = max(1, max_work_orders_for_date)
    
    # Step 2: Initialize summary data structure
    summary_data = {
        'daily_data': [],
        'weekly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Initialize daily summary with dynamic columns per day
    for date in date_range:
        summary_data['daily_data'].append({
            'date': date,
            'columns_count': columns_per_day[date],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        })
    
    # Step 3: Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'daily_data': [],
            'weekly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each date for this machine
        for date_index, date in enumerate(date_range):
            columns_for_this_date = columns_per_day[date]
            
            # Get work orders for this machine and date
            headers_for_date = weld_headers.filter(machine=machine, date=date)
            
            # Get booked hours from header - per shift
            booked_hours_by_shift = {}
            for header in headers_for_date:
                shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                if header.booked_hours and header.booked_hours.duration:
                    if shift_name not in booked_hours_by_shift:
                        booked_hours_by_shift[shift_name] = 0
                    booked_hours_by_shift[shift_name] += float(header.booked_hours.duration)
            
            # Total booked hours for the day
            booked_hours_from_header = sum(booked_hours_by_shift.values())
            
            # Collect work order data - separate by work_order + shift
            work_order_shift_list = []  # List of (work_order, shift_name) tuples
            work_order_shift_data = {}  # Key: (work_order, shift_name)
            
            for header in headers_for_date:
                shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                details = WeldDetail.objects.filter(Reff=header).select_related('bjo', 'bjo__size', 'bjo__conn')
                
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        work_order = detail.bjo.bjo
                        
                        # Create unique key with shift
                        work_order_shift_key = (work_order, shift_name)
                        
                        if work_order_shift_key not in work_order_shift_list:
                            work_order_shift_list.append(work_order_shift_key)
                        
                        if work_order_shift_key not in work_order_shift_data:
                            # Clean size display
                            size_display = str(detail.bjo.size) if detail.bjo.size else ''
                            if size_display:
                                size_display = size_display.replace('THREADING', '').replace('WELDING', '').strip()
                            
                            work_order_shift_data[work_order_shift_key] = {
                                'header': header,
                                'shift': shift_name,
                                'details': [],
                                'client': detail.bjo.customer if detail.bjo.customer else '',
                                'size': size_display,
                                'connection': detail.bjo.conn.name if detail.bjo.conn else '',
                                'cycle_time': str(detail.ct) if detail.ct else '',
                                'actual_hours': 0,
                                'output_qty': 0,
                                'non_recordable_time': 0,
                                'booked_hours_for_shift': 0,
                                'is_posted': header.is_posted,  # Track if header is posted
                            }
                        work_order_shift_data[work_order_shift_key]['details'].append(detail)
            
            # Sort work_order_shift_list by shift order (SHIFT 1 first, then SHIFT 2, then others)
            def shift_sort_key(item):
                work_order, shift_name = item
                # Priority: SHIFT 1 = 1, SHIFT 2 = 2, others = 3
                if 'SHIFT 1' in shift_name or 'Shift 1' in shift_name:
                    return (1, work_order)
                elif 'SHIFT 2' in shift_name or 'Shift 2' in shift_name:
                    return (2, work_order)
                else:
                    return (3, shift_name, work_order)
            
            work_order_shift_list.sort(key=shift_sort_key)
            
            # Calculate actual hours, non-recordable time, and output qty for each work order-shift combination
            for work_order_shift_key in work_order_shift_data:
                wo_data = work_order_shift_data[work_order_shift_key]
                details = wo_data['details']
                header = wo_data['header']
                
                total_hours = 0
                total_output = 0
                
                # Calculate hours from start/stop times using calculate_time_duration
                for detail in details:
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours is not None:
                            total_hours += hours
                    
                    # Calculate output from field output in detail
                    if detail.output:
                        total_output += float(detail.output)
                
                # Get reason stops (Weld has only one type per header, no bjo field)
                reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
                
                # Calculate non-recordable time from reason stops
                total_non_recordable = 0
                if reason_stops:
                    total_non_recordable = (
                        float(reason_stops.waiting_materials or 0) +
                        float(reason_stops.meeting or 0) +
                        float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) +
                        float(reason_stops.others or 0)
                    )
                
                wo_data['actual_hours'] = total_hours
                wo_data['output_qty'] = total_output
                wo_data['non_recordable_time'] = total_non_recordable
                wo_data['reason_stops'] = reason_stops  # Store for later use
            
            # DISTRIBUSI BOOKED HOURS - METODE PLANNED HOURS (Output × CT)
            planned_hours_per_shift = {}
            work_orders_per_shift = {}
            
            for work_order_shift_key, wo_data in work_order_shift_data.items():
                shift_name = wo_data['shift']
                
                if shift_name not in planned_hours_per_shift:
                    planned_hours_per_shift[shift_name] = 0
                    work_orders_per_shift[shift_name] = []
                
                # Calculate planned hours = Output × Cycle Time
                planned_hours_for_wo = 0
                if wo_data['output_qty'] > 0 and wo_data['cycle_time']:
                    try:
                        cycle_time = float(wo_data['cycle_time'])
                        if cycle_time > 0:
                            planned_hours_for_wo = wo_data['output_qty'] * cycle_time
                    except (ValueError, TypeError):
                        planned_hours_for_wo = 0
                
                wo_data['planned_hours'] = planned_hours_for_wo
                planned_hours_per_shift[shift_name] += planned_hours_for_wo
                work_orders_per_shift[shift_name].append(work_order_shift_key)
            
            # Distribute booked hours to each work order based on planned hours
            for shift_name, total_planned_hours in planned_hours_per_shift.items():
                booked_hours_for_shift = booked_hours_by_shift.get(shift_name, 0)
                work_orders_in_shift = work_orders_per_shift[shift_name]
                
                if total_planned_hours > 0:
                    # PROPORTIONAL distribution based on planned hours
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        proportion = wo_data['planned_hours'] / total_planned_hours
                        wo_data['booked_hours_for_shift'] = booked_hours_for_shift * proportion
                else:
                    # EQUAL distribution if no planned hours
                    num_work_orders = len(work_orders_in_shift)
                    allocated_hours = booked_hours_for_shift / num_work_orders if num_work_orders > 0 else 0
                    
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        wo_data['booked_hours_for_shift'] = allocated_hours
            
            # Initialize daily data with correct column count for this date
            daily_data = {
                'date': date,
                'columns_count': columns_for_this_date,
                'booked_hours_header': booked_hours_from_header,
                'booked_hours_distributed': [0] * columns_for_this_date,
                'work_orders': [''] * columns_for_this_date,
                'shifts': [''] * columns_for_this_date,
                'clients': [''] * columns_for_this_date,
                'sizes': [''] * columns_for_this_date,
                'connections': [''] * columns_for_this_date,
                'cycle_times': [''] * columns_for_this_date,
                'working_hours': [0] * columns_for_this_date,
                'planned_production': [0] * columns_for_this_date,
                'output_qty': [0] * columns_for_this_date,
                'rejects': [0] * columns_for_this_date,
                'cutbacks': [0] * columns_for_this_date,
                'oee': [0] * columns_for_this_date,
                'reject_rate': [0] * columns_for_this_date,
                'operating_hours': [0] * columns_for_this_date,
                'non_recorded_time': [0] * columns_for_this_date,
                'wait_material': [0] * columns_for_this_date,
                'meetings': [0] * columns_for_this_date,
                'breakdown': [0] * columns_for_this_date,
                'change_over': [0] * columns_for_this_date,
                'availability': [0] * columns_for_this_date,
                'performance': [0] * columns_for_this_date,
                'quality': [0] * columns_for_this_date,
                'total_working_hours': 0,
                'total_output_qty': 0,
                'is_posted': [True] * columns_for_this_date,  # Track posted status for each column
            }
            
            # Fill data for each work order-shift combination
            for i, work_order_shift_key in enumerate(work_order_shift_list):
                if i < columns_for_this_date and work_order_shift_key in work_order_shift_data:
                    wo_data = work_order_shift_data[work_order_shift_key]
                    header = wo_data['header']
                    work_order, shift_name = work_order_shift_key
                    reason_stops = wo_data.get('reason_stops')
                    
                    daily_data['work_orders'][i] = work_order
                    daily_data['shifts'][i] = shift_name
                    daily_data['clients'][i] = wo_data['client']
                    daily_data['sizes'][i] = wo_data['size']
                    daily_data['connections'][i] = wo_data['connection']
                    daily_data['cycle_times'][i] = wo_data['cycle_time']
                    daily_data['working_hours'][i] = wo_data['actual_hours']
                    daily_data['output_qty'][i] = wo_data['output_qty']
                    daily_data['booked_hours_distributed'][i] = wo_data['booked_hours_for_shift']
                    daily_data['is_posted'][i] = wo_data['is_posted']  # Set posted status
                    
                    # Set reject and cutback from reason stops
                    if reason_stops:
                        daily_data['rejects'][i] = float(reason_stops.reject or 0)
                        daily_data['cutbacks'][i] = float(reason_stops.cutback or 0)
                    else:
                        daily_data['rejects'][i] = 0
                        daily_data['cutbacks'][i] = 0
                    
                    # Set reason stops (distributed equally across all work orders in the shift)
                    # Get count of work orders in this shift for distribution
                    work_orders_in_shift_count = len([k for k in work_order_shift_list if k[1] == shift_name])
                    
                    if reason_stops and work_orders_in_shift_count > 0:
                        daily_data['wait_material'][i] = float(reason_stops.waiting_materials or 0) / work_orders_in_shift_count
                        daily_data['meetings'][i] = float(reason_stops.meeting or 0) / work_orders_in_shift_count
                        daily_data['breakdown'][i] = float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) / work_orders_in_shift_count
                        daily_data['change_over'][i] = float(reason_stops.others or 0) / work_orders_in_shift_count
                    else:
                        daily_data['wait_material'][i] = 0
                        daily_data['meetings'][i] = 0
                        daily_data['breakdown'][i] = 0
                        daily_data['change_over'][i] = 0
                    
                    # Calculate downtime
                    total_downtime = (
                        daily_data['wait_material'][i] + 
                        daily_data['meetings'][i] + 
                        daily_data['breakdown'][i] + 
                        daily_data['change_over'][i]
                    )
                    daily_data['non_recorded_time'][i] = total_downtime
                    
                    # OEE CALCULATION (SAMA DENGAN THREAD - SIMPLIFIED FORMULA)
                    booked_hours_for_this_wo = wo_data['booked_hours_for_shift']
                    
                    try:
                        if (booked_hours_for_this_wo > 0 and 
                            daily_data['cycle_times'][i] and 
                            float(daily_data['cycle_times'][i]) > 0 and
                            daily_data['output_qty'][i] > 0):
                            
                            cycle_time = float(daily_data['cycle_times'][i])
                            output = daily_data['output_qty'][i]
                            rejects = daily_data['rejects'][i]
                            cutbacks = daily_data['cutbacks'][i]
                            
                            # Good Output = Output - Reject - Cutback
                            good_output = output - rejects - cutbacks
                            good_output = max(0, good_output)
                            
                            # OEE = ((Good Output × CT) / Booked Hours) × 100%
                            if booked_hours_for_this_wo > 0:
                                oee_value = ((good_output * cycle_time) / booked_hours_for_this_wo) * 100
                                oee_value = max(0, min(oee_value, 100))
                            else:
                                oee_value = 0
                            
                            daily_data['oee'][i] = round(oee_value, 2)
                            
                            # Clear availability, performance, quality karena tidak digunakan lagi
                            daily_data['availability'][i] = 0
                            daily_data['performance'][i] = 0
                            daily_data['quality'][i] = 0
                        else:
                            daily_data['availability'][i] = 0
                            daily_data['performance'][i] = 0
                            daily_data['quality'][i] = 0
                            daily_data['oee'][i] = 0
                    except (ZeroDivisionError, ValueError, TypeError):
                        daily_data['availability'][i] = 0
                        daily_data['performance'][i] = 0
                        daily_data['quality'][i] = 0
                        daily_data['oee'][i] = 0
                    
                    # Calculate operating hours
                    daily_data['operating_hours'][i] = max(0, daily_data['working_hours'][i] - daily_data['non_recorded_time'][i])
                    
                    # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
                    total_production = daily_data['output_qty'][i] + daily_data['rejects'][i] + daily_data['cutbacks'][i]
                    if total_production > 0:
                        daily_data['reject_rate'][i] = ((daily_data['rejects'][i] + daily_data['cutbacks'][i]) / total_production * 100)
                    else:
                        daily_data['reject_rate'][i] = 0
                    
                    # Calculate planned production based on distributed booked hours
                    if daily_data['cycle_times'][i] and booked_hours_for_this_wo > 0:
                        try:
                            cycle_time = float(daily_data['cycle_times'][i])
                            if cycle_time > 0:
                                daily_data['planned_production'][i] = booked_hours_for_this_wo / cycle_time
                        except (ValueError, TypeError):
                            daily_data['planned_production'][i] = 0
                    
                    # ===== ONLY ACCUMULATE TO WEEKLY IF POSTED =====
                    if wo_data['is_posted']:
                        machine_info['weekly_totals']['total_output_qty'] += daily_data['output_qty'][i]
                        machine_info['weekly_totals']['total_working_hours'] += daily_data['working_hours'][i]
                        machine_info['weekly_totals']['total_planned_production'] += daily_data['planned_production'][i]
                        machine_info['weekly_totals']['total_rejects'] += daily_data['rejects'][i]
                        machine_info['weekly_totals']['total_cutbacks'] += daily_data['cutbacks'][i]
                        machine_info['weekly_totals']['total_wait_material'] += daily_data['wait_material'][i]
                        machine_info['weekly_totals']['total_meetings'] += daily_data['meetings'][i]
                        machine_info['weekly_totals']['total_breakdown'] += daily_data['breakdown'][i]
                        machine_info['weekly_totals']['total_change_over'] += daily_data['change_over'][i]
                        machine_info['weekly_totals']['total_operating_hours'] += daily_data['operating_hours'][i]
                        machine_info['weekly_totals']['total_non_recorded_time'] += daily_data['non_recorded_time'][i]
                        
                        # Update summary data
                        summary_data['daily_data'][date_index]['working_hours'] += daily_data['working_hours'][i]
                        summary_data['daily_data'][date_index]['planned_production'] += daily_data['planned_production'][i]
                        summary_data['daily_data'][date_index]['output_qty'] += daily_data['output_qty'][i]
                        summary_data['daily_data'][date_index]['rejects'] += daily_data['rejects'][i]
                        summary_data['daily_data'][date_index]['cutbacks'] += daily_data['cutbacks'][i]
                        summary_data['daily_data'][date_index]['wait_material'] += daily_data['wait_material'][i]
                        summary_data['daily_data'][date_index]['meetings'] += daily_data['meetings'][i]
                        summary_data['daily_data'][date_index]['breakdown'] += daily_data['breakdown'][i]
                        summary_data['daily_data'][date_index]['change_over'] += daily_data['change_over'][i]
                        summary_data['daily_data'][date_index]['operating_hours'] += daily_data['operating_hours'][i]
                        summary_data['daily_data'][date_index]['non_recorded_time'] += daily_data['non_recorded_time'][i]
                        
                        # Accumulate for averages
                        if daily_data['oee'][i] > 0:
                            total_oee_sum += daily_data['oee'][i]
                            total_oee_count += 1
                        
                        if daily_data['reject_rate'][i] >= 0:
                            total_reject_rate_sum += daily_data['reject_rate'][i]
                            total_reject_rate_count += 1
            
            # ===== ONLY ACCUMULATE BOOKED HOURS IF POSTED =====
            for header in headers_for_date:
                if header.is_posted:
                    shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                    if header.booked_hours and header.booked_hours.duration:
                        booked_hours_value = float(header.booked_hours.duration)
                        machine_info['weekly_totals']['total_booked_hours_header'] += booked_hours_value
                        summary_data['daily_data'][date_index]['booked_hours_header'] += booked_hours_value
            
            # Calculate daily totals
            daily_data['total_working_hours'] = sum(daily_data['working_hours'])
            daily_data['total_output_qty'] = sum(daily_data['output_qty'])
            
            machine_info['daily_data'].append(daily_data)
        
        # Calculate machine averages
        machine_info['weekly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['weekly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets and calculate variance/percentage
        weekly_totals = machine_info['weekly_totals']
        
        # Define targets
        weekly_totals['target_booked_hours_header'] = 105.0
        weekly_totals['target_working_hours'] = 105.0
        weekly_totals['target_output_qty'] = 85.0
        weekly_totals['target_oee'] = 85.0
        weekly_totals['target_reject_rate'] = 1.5
        weekly_totals['target_wait_material'] = 1.7
        weekly_totals['target_meetings'] = 0.8
        weekly_totals['target_breakdown'] = 1.7
        weekly_totals['target_change_over'] = 4.2
        weekly_totals['target_operating_hours'] = 84.0
        weekly_totals['target_non_recorded_time'] = 8.4
        
        # Calculate variances
        weekly_totals['variance_booked_hours_header'] = round(weekly_totals['total_booked_hours_header'] - weekly_totals['target_booked_hours_header'], 1) if weekly_totals['total_booked_hours_header'] > 0 else None
        weekly_totals['variance_working_hours'] = round(weekly_totals['total_working_hours'] - weekly_totals['target_working_hours'], 1) if weekly_totals['total_working_hours'] > 0 else None
        weekly_totals['variance_output_qty'] = round(weekly_totals['total_output_qty'] - weekly_totals['target_output_qty'], 1) if weekly_totals['total_output_qty'] > 0 else None
        weekly_totals['variance_oee'] = round(weekly_totals['average_oee'] - weekly_totals['target_oee'], 1) if weekly_totals['average_oee'] > 0 else None
        weekly_totals['variance_reject_rate'] = round(weekly_totals['average_reject_rate'] - weekly_totals['target_reject_rate'], 1) if weekly_totals['average_reject_rate'] >= 0 else None
        weekly_totals['variance_wait_material'] = round(weekly_totals['total_wait_material'] - weekly_totals['target_wait_material'], 1) if weekly_totals['total_wait_material'] > 0 else None
        weekly_totals['variance_meetings'] = round(weekly_totals['total_meetings'] - weekly_totals['target_meetings'], 1) if weekly_totals['total_meetings'] > 0 else None
        weekly_totals['variance_breakdown'] = round(weekly_totals['total_breakdown'] - weekly_totals['target_breakdown'], 1) if weekly_totals['total_breakdown'] > 0 else None
        weekly_totals['variance_change_over'] = round(weekly_totals['total_change_over'] - weekly_totals['target_change_over'], 1) if weekly_totals['total_change_over'] > 0 else None
        weekly_totals['variance_operating_hours'] = round(weekly_totals['total_operating_hours'] - weekly_totals['target_operating_hours'], 1) if weekly_totals['total_operating_hours'] > 0 else None
        weekly_totals['variance_non_recorded_time'] = round(weekly_totals['total_non_recorded_time'] - weekly_totals['target_non_recorded_time'], 1) if weekly_totals['total_non_recorded_time'] > 0 else None
        
        # Calculate percentages
        weekly_totals['percent_booked_hours_header'] = round((weekly_totals['total_booked_hours_header'] / weekly_totals['target_booked_hours_header']) * 100, 1) if weekly_totals['total_booked_hours_header'] > 0 and weekly_totals['target_booked_hours_header'] > 0 else None
        weekly_totals['percent_working_hours'] = round((weekly_totals['total_working_hours'] / weekly_totals['target_working_hours']) * 100, 1) if weekly_totals['total_working_hours'] > 0 and weekly_totals['target_working_hours'] > 0 else None
        weekly_totals['percent_output_qty'] = round((weekly_totals['total_output_qty'] / weekly_totals['target_output_qty']) * 100, 1) if weekly_totals['total_output_qty'] > 0 and weekly_totals['target_output_qty'] > 0 else None
        weekly_totals['percent_oee'] = round((weekly_totals['average_oee'] / weekly_totals['target_oee']) * 100, 1) if weekly_totals['average_oee'] > 0 and weekly_totals['target_oee'] > 0 else None
        weekly_totals['percent_wait_material'] = round((weekly_totals['total_wait_material'] / weekly_totals['target_wait_material']) * 100, 1) if weekly_totals['total_wait_material'] > 0 and weekly_totals['target_wait_material'] > 0 else None
        weekly_totals['percent_meetings'] = round((weekly_totals['total_meetings'] / weekly_totals['target_meetings']) * 100, 1) if weekly_totals['total_meetings'] > 0 and weekly_totals['target_meetings'] > 0 else None
        weekly_totals['percent_breakdown'] = round((weekly_totals['total_breakdown'] / weekly_totals['target_breakdown']) * 100, 1) if weekly_totals['total_breakdown'] > 0 and weekly_totals['target_breakdown'] > 0 else None
        weekly_totals['percent_change_over'] = round((weekly_totals['total_change_over'] / weekly_totals['target_change_over']) * 100, 1) if weekly_totals['total_change_over'] > 0 and weekly_totals['target_change_over'] > 0 else None
        weekly_totals['percent_operating_hours'] = round((weekly_totals['total_operating_hours'] / weekly_totals['target_operating_hours']) * 100, 1) if weekly_totals['total_operating_hours'] > 0 and weekly_totals['target_operating_hours'] > 0 else None
        weekly_totals['percent_non_recorded_time'] = round((weekly_totals['total_non_recorded_time'] / weekly_totals['target_non_recorded_time']) * 100, 1) if weekly_totals['total_non_recorded_time'] > 0 and weekly_totals['target_non_recorded_time'] > 0 else None
        
        machine_data.append(machine_info)
    
    # Step 4: Calculate summary totals and averages (ONLY FROM POSTED DATA)
    total_oee_values = []
    total_reject_rates = []
    
    for daily_summary in summary_data['daily_data']:
        if daily_summary['booked_hours_header'] > 0:
            daily_oee_values = []
            daily_reject_total = 0
            daily_cutback_total = 0
            daily_output_total = 0
            
            for machine_info in machine_data:
                for daily_data in machine_info['daily_data']:
                    if daily_data['date'] == daily_summary['date']:
                        # Only count posted data
                        for idx, oee_val in enumerate(daily_data['oee']):
                            if oee_val > 0 and daily_data['is_posted'][idx]:
                                daily_oee_values.append(oee_val)
                        
                        # Only count posted data for reject rate
                        for idx in range(len(daily_data['rejects'])):
                            if daily_data['is_posted'][idx]:
                                daily_reject_total += daily_data['rejects'][idx]
                                daily_cutback_total += daily_data['cutbacks'][idx]
                                daily_output_total += daily_data['output_qty'][idx]
            
            daily_summary['oee'] = round(sum(daily_oee_values) / len(daily_oee_values), 2) if daily_oee_values else 0
            
            # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = daily_output_total + daily_reject_total + daily_cutback_total
            if total_production > 0:
                daily_summary['reject_rate'] = round(((daily_reject_total + daily_cutback_total) / total_production * 100), 2)
            else:
                daily_summary['reject_rate'] = 0
            
            if daily_summary['oee'] > 0:
                total_oee_values.append(daily_summary['oee'])
            if daily_summary['reject_rate'] >= 0:
                total_reject_rates.append(daily_summary['reject_rate'])
    
    # Calculate weekly summary totals
    summary_data['weekly_totals']['total_booked_hours_header'] = sum([d['booked_hours_header'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_working_hours'] = sum([d['working_hours'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_planned_production'] = sum([d['planned_production'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_output_qty'] = sum([d['output_qty'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_rejects'] = sum([d['rejects'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_cutbacks'] = sum([d['cutbacks'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_wait_material'] = sum([d['wait_material'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_meetings'] = sum([d['meetings'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_breakdown'] = sum([d['breakdown'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_change_over'] = sum([d['change_over'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_operating_hours'] = sum([d['operating_hours'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['total_non_recorded_time'] = sum([d['non_recorded_time'] for d in summary_data['daily_data']])
    summary_data['weekly_totals']['average_oee'] = round(sum(total_oee_values) / len(total_oee_values), 2) if total_oee_values else 0
    summary_data['weekly_totals']['average_reject_rate'] = round(sum(total_reject_rates) / len(total_reject_rates), 2) if total_reject_rates else 0
    
    # Add summary targets
    summary_data['weekly_totals']['target_booked_hours_header'] = 315.0
    summary_data['weekly_totals']['target_working_hours'] = 315.0
    summary_data['weekly_totals']['target_output_qty'] = 255.0
    summary_data['weekly_totals']['target_oee'] = 85.0
    summary_data['weekly_totals']['target_reject_rate'] = 1.5
    summary_data['weekly_totals']['target_wait_material'] = 5.1
    summary_data['weekly_totals']['target_meetings'] = 2.4
    summary_data['weekly_totals']['target_breakdown'] = 5.1
    summary_data['weekly_totals']['target_change_over'] = 12.6
    summary_data['weekly_totals']['target_operating_hours'] = 252.0
    summary_data['weekly_totals']['target_non_recorded_time'] = 25.2
    
    # Calculate summary variance and percentage
    summary_totals = summary_data['weekly_totals']
    summary_totals['variance_booked_hours_header'] = round(summary_totals['total_booked_hours_header'] - summary_totals['target_booked_hours_header'], 1) if summary_totals['total_booked_hours_header'] > 0 else None
    summary_totals['variance_working_hours'] = round(summary_totals['total_working_hours'] - summary_totals['target_working_hours'], 1) if summary_totals['total_working_hours'] > 0 else None
    summary_totals['variance_output_qty'] = round(summary_totals['total_output_qty'] - summary_totals['target_output_qty'], 1) if summary_totals['total_output_qty'] > 0 else None
    summary_totals['variance_oee'] = round(summary_totals['average_oee'] - summary_totals['target_oee'], 1) if summary_totals['average_oee'] > 0 else None
    summary_totals['variance_reject_rate'] = round(summary_totals['average_reject_rate'] - summary_totals['target_reject_rate'], 1) if summary_totals['average_reject_rate'] >= 0 else None
    summary_totals['variance_wait_material'] = round(summary_totals['total_wait_material'] - summary_totals['target_wait_material'], 1) if summary_totals['total_wait_material'] > 0 else None
    summary_totals['variance_meetings'] = round(summary_totals['total_meetings'] - summary_totals['target_meetings'], 1) if summary_totals['total_meetings'] > 0 else None
    summary_totals['variance_breakdown'] = round(summary_totals['total_breakdown'] - summary_totals['target_breakdown'], 1) if summary_totals['total_breakdown'] > 0 else None
    summary_totals['variance_change_over'] = round(summary_totals['total_change_over'] - summary_totals['target_change_over'], 1) if summary_totals['total_change_over'] > 0 else None
    summary_totals['variance_operating_hours'] = round(summary_totals['total_operating_hours'] - summary_totals['target_operating_hours'], 1) if summary_totals['total_operating_hours'] > 0 else None
    summary_totals['variance_non_recorded_time'] = round(summary_totals['total_non_recorded_time'] - summary_totals['target_non_recorded_time'], 1) if summary_totals['total_non_recorded_time'] > 0 else None
    
    # Calculate summary percentages
    summary_totals['percent_booked_hours_header'] = round((summary_totals['total_booked_hours_header'] / summary_totals['target_booked_hours_header']) * 100, 1) if summary_totals['total_booked_hours_header'] > 0 and summary_totals['target_booked_hours_header'] > 0 else None
    summary_totals['percent_working_hours'] = round((summary_totals['total_working_hours'] / summary_totals['target_working_hours']) * 100, 1) if summary_totals['total_working_hours'] > 0 and summary_totals['target_working_hours'] > 0 else None
    summary_totals['percent_output_qty'] = round((summary_totals['total_output_qty'] / summary_totals['target_output_qty']) * 100, 1) if summary_totals['total_output_qty'] > 0 and summary_totals['target_output_qty'] > 0 else None
    summary_totals['percent_oee'] = round((summary_totals['average_oee'] / summary_totals['target_oee']) * 100, 1) if summary_totals['average_oee'] > 0 and summary_totals['target_oee'] > 0 else None
    summary_totals['percent_wait_material'] = round((summary_totals['total_wait_material'] / summary_totals['target_wait_material']) * 100, 1) if summary_totals['total_wait_material'] > 0 and summary_totals['target_wait_material'] > 0 else None
    summary_totals['percent_meetings'] = round((summary_totals['total_meetings'] / summary_totals['target_meetings']) * 100, 1) if summary_totals['total_meetings'] > 0 and summary_totals['target_meetings'] > 0 else None
    summary_totals['percent_breakdown'] = round((summary_totals['total_breakdown'] / summary_totals['target_breakdown']) * 100, 1) if summary_totals['total_breakdown'] > 0 and summary_totals['target_breakdown'] > 0 else None
    summary_totals['percent_change_over'] = round((summary_totals['total_change_over'] / summary_totals['target_change_over']) * 100, 1) if summary_totals['total_change_over'] > 0 and summary_totals['target_change_over'] > 0 else None
    summary_totals['percent_operating_hours'] = round((summary_totals['total_operating_hours'] / summary_totals['target_operating_hours']) * 100, 1) if summary_totals['total_operating_hours'] > 0 and summary_totals['target_operating_hours'] > 0 else None
    summary_totals['percent_non_recorded_time'] = round((summary_totals['total_non_recorded_time'] / summary_totals['target_non_recorded_time']) * 100, 1) if summary_totals['total_non_recorded_time'] > 0 and summary_totals['target_non_recorded_time'] > 0 else None
    
    # Create week days labels
    week_days_labels = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    
    # Prepare context
    context = {
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        'week_number': week_number,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'week_days': week_days_labels,
        'columns_per_day': columns_per_day,
        'active_menu':'weld_report_oee'
    }
    
    return render(request, 'weld/report_oee.html', context)

@threading_report_access_required
def thread_report_oee_monthly(request):
    """
    Monthly OEE Report - Shows weekly summaries for each week in a month
    UPDATED: New OEE formula = ((Output - (Reject + Cutback)) × CT) / Booked Hours × 100%
    """
    # Get month and year from request or default to current month
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    if not month or not year:
        today = datetime.now().date()
        month = today.month
        year = today.year
    else:
        month = int(month)
        year = int(year)
    
    # Get first and last day of the month
    first_day = datetime(year, month, 1).date()
    if month == 12:
        last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        last_day = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    # Find all Sunday-Saturday weeks in this month
    weeks = []
    current_date = first_day
    
    # Find first Sunday
    days_since_sunday = (current_date.weekday() + 1) % 7
    week_start = current_date - timedelta(days=days_since_sunday)
    
    while week_start <= last_day:
        week_end = week_start + timedelta(days=6)
        week_number = week_start.isocalendar()[1] + 1
        
        # Only include weeks that have at least one day in the current month
        if week_end >= first_day and week_start <= last_day:
            weeks.append({
                'week_number': week_number,
                'start_date': week_start,
                'end_date': week_end
            })
        
        week_start += timedelta(days=7)
    
    # Get all machines
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    machines = Machine.objects.filter(process_type=threading_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'weekly_data': [],
            'monthly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_absorption_hours': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each week
        for week in weeks:
            # Get thread headers for this week
            thread_headers = ThreadHeader.objects.filter(
                machine=machine,
                date__range=[week['start_date'], week['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize weekly data
            weekly_summary = {
                'week_number': week['week_number'],
                'start_date': week['start_date'],
                'end_date': week['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'absorption_hours': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
                'total_cycle_time_output': 0,  # For OEE calculation
            }
            
            # Calculate totals from headers
            for header in thread_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    weekly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            weekly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        weekly_summary['output_qty'] += float(detail.output)
                    
                    # For OEE: accumulate (Output × CT)
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            weekly_summary['total_cycle_time_output'] += (output * ct)
                        except (ValueError, TypeError):
                            pass
                    
                    # Planned production
                    if detail.ct and weekly_summary['booked_hours_header'] > 0:
                        try:
                            ct = float(detail.ct)
                            if ct > 0:
                                weekly_summary['planned_production'] += weekly_summary['booked_hours_header'] / ct
                        except (ValueError, TypeError):
                            pass
                    
                    # Absorption hours
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            process_rate = 0
                            if machine.process_type and machine.process_type.rate:
                                process_rate = float(machine.process_type.rate)
                            weekly_summary['absorption_hours'] += process_rate * (ct * output)
                        except (ValueError, TypeError):
                            pass
                
                # Reason stops
                reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    weekly_summary['rejects'] += float(reason_stops.reject or 0)
                    weekly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    weekly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    weekly_summary['meetings'] += float(reason_stops.meeting or 0)
                    weekly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    weekly_summary['change_over'] += float(reason_stops.change_over or 0)
            
            # Calculate non-recorded time
            weekly_summary['non_recorded_time'] = (
                weekly_summary['wait_material'] + 
                weekly_summary['meetings'] + 
                weekly_summary['breakdown'] + 
                weekly_summary['change_over']
            )
            
            # Calculate operating hours
            weekly_summary['operating_hours'] = max(0, weekly_summary['working_hours'] - weekly_summary['non_recorded_time'])
            
            # ========================================
            # NEW OEE CALCULATION FOR WEEKLY AGGREGATE
            # OEE = ((Output - Reject - Cutback) × CT) / Booked Hours × 100%
            # ========================================
            if weekly_summary['booked_hours_header'] > 0 and weekly_summary['output_qty'] > 0:
                good_output = weekly_summary['output_qty'] - weekly_summary['rejects'] - weekly_summary['cutbacks']
                good_output = max(0, good_output)
                
                # Calculate good output ratio
                good_output_ratio = good_output / weekly_summary['output_qty'] if weekly_summary['output_qty'] > 0 else 0
                
                # Apply ratio to total_cycle_time_output
                good_cycle_time_output = weekly_summary['total_cycle_time_output'] * good_output_ratio
                
                if weekly_summary['booked_hours_header'] > 0:
                    oee_value = (good_cycle_time_output / weekly_summary['booked_hours_header']) * 100
                    oee_value = max(0, min(oee_value, 100))  # Cap between 0-100%
                else:
                    oee_value = 0
                
                weekly_summary['oee'] = round(oee_value, 2)
            else:
                weekly_summary['oee'] = 0
            
            # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = weekly_summary['output_qty'] + weekly_summary['rejects'] + weekly_summary['cutbacks']
            if total_production > 0:
                weekly_summary['reject_rate'] = round(((weekly_summary['rejects'] + weekly_summary['cutbacks']) / total_production * 100), 2)
            else:
                weekly_summary['reject_rate'] = 0
            
            # Add to machine's weekly data
            machine_info['weekly_data'].append(weekly_summary)
            
            # Accumulate monthly totals
            machine_info['monthly_totals']['total_booked_hours_header'] += weekly_summary['booked_hours_header']
            machine_info['monthly_totals']['total_working_hours'] += weekly_summary['working_hours']
            machine_info['monthly_totals']['total_planned_production'] += weekly_summary['planned_production']
            machine_info['monthly_totals']['total_output_qty'] += weekly_summary['output_qty']
            machine_info['monthly_totals']['total_rejects'] += weekly_summary['rejects']
            machine_info['monthly_totals']['total_cutbacks'] += weekly_summary['cutbacks']
            machine_info['monthly_totals']['total_absorption_hours'] += weekly_summary['absorption_hours']
            machine_info['monthly_totals']['total_wait_material'] += weekly_summary['wait_material']
            machine_info['monthly_totals']['total_meetings'] += weekly_summary['meetings']
            machine_info['monthly_totals']['total_breakdown'] += weekly_summary['breakdown']
            machine_info['monthly_totals']['total_change_over'] += weekly_summary['change_over']
            machine_info['monthly_totals']['total_operating_hours'] += weekly_summary['operating_hours']
            machine_info['monthly_totals']['total_non_recorded_time'] += weekly_summary['non_recorded_time']
            
            if weekly_summary['oee'] > 0:
                total_oee_sum += weekly_summary['oee']
                total_oee_count += 1
            
            if weekly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += weekly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate monthly averages
        machine_info['monthly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['monthly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply weekly targets by number of weeks)
        num_weeks = len(weeks)
        machine_info['monthly_totals']['target_booked_hours_header'] = 105.0 * num_weeks
        machine_info['monthly_totals']['target_working_hours'] = 105.0 * num_weeks
        machine_info['monthly_totals']['target_output_qty'] = 85.0 * num_weeks
        machine_info['monthly_totals']['target_oee'] = 85.0
        machine_info['monthly_totals']['target_reject_rate'] = 1.5
        machine_info['monthly_totals']['target_absorption_hours'] = 16762.20 * num_weeks
        
        # Calculate variances
        machine_info['monthly_totals']['variance_booked_hours_header'] = round(machine_info['monthly_totals']['total_booked_hours_header'] - machine_info['monthly_totals']['target_booked_hours_header'], 1)
        machine_info['monthly_totals']['variance_working_hours'] = round(machine_info['monthly_totals']['total_working_hours'] - machine_info['monthly_totals']['target_working_hours'], 1)
        machine_info['monthly_totals']['variance_output_qty'] = round(machine_info['monthly_totals']['total_output_qty'] - machine_info['monthly_totals']['target_output_qty'], 1)
        machine_info['monthly_totals']['variance_oee'] = round(machine_info['monthly_totals']['average_oee'] - machine_info['monthly_totals']['target_oee'], 1)
        machine_info['monthly_totals']['variance_reject_rate'] = round(machine_info['monthly_totals']['average_reject_rate'] - machine_info['monthly_totals']['target_reject_rate'], 1)
        
        # Calculate percentages
        machine_info['monthly_totals']['percent_booked_hours_header'] = round((machine_info['monthly_totals']['total_booked_hours_header'] / machine_info['monthly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['monthly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['monthly_totals']['percent_working_hours'] = round((machine_info['monthly_totals']['total_working_hours'] / machine_info['monthly_totals']['target_working_hours']) * 100, 1) if machine_info['monthly_totals']['target_working_hours'] > 0 else 0
        machine_info['monthly_totals']['percent_output_qty'] = round((machine_info['monthly_totals']['total_output_qty'] / machine_info['monthly_totals']['target_output_qty']) * 100, 1) if machine_info['monthly_totals']['target_output_qty'] > 0 else 0
        machine_info['monthly_totals']['percent_oee'] = round((machine_info['monthly_totals']['average_oee'] / machine_info['monthly_totals']['target_oee']) * 100, 1) if machine_info['monthly_totals']['target_oee'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'weekly_data': [],
        'monthly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_absorption_hours': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate weekly summaries across all machines
    for week in weeks:
        week_summary = {
            'week_number': week['week_number'],
            'start_date': week['start_date'],
            'end_date': week['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'absorption_hours': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for weekly_data in machine_info['weekly_data']:
                if weekly_data['week_number'] == week['week_number']:
                    week_summary['booked_hours_header'] += weekly_data['booked_hours_header']
                    week_summary['working_hours'] += weekly_data['working_hours']
                    week_summary['planned_production'] += weekly_data['planned_production']
                    week_summary['output_qty'] += weekly_data['output_qty']
                    week_summary['rejects'] += weekly_data['rejects']
                    week_summary['cutbacks'] += weekly_data['cutbacks']
                    week_summary['absorption_hours'] += weekly_data['absorption_hours']
                    week_summary['wait_material'] += weekly_data['wait_material']
                    week_summary['meetings'] += weekly_data['meetings']
                    week_summary['breakdown'] += weekly_data['breakdown']
                    week_summary['change_over'] += weekly_data['change_over']
                    week_summary['operating_hours'] += weekly_data['operating_hours']
                    week_summary['non_recorded_time'] += weekly_data['non_recorded_time']
                    
                    if weekly_data['oee'] > 0:
                        oee_values.append(weekly_data['oee'])
                    if weekly_data['reject_rate'] >= 0:
                        reject_rates.append(weekly_data['reject_rate'])
        
        week_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # Calculate reject rate for summary
        total_production = week_summary['output_qty'] + week_summary['rejects'] + week_summary['cutbacks']
        if total_production > 0:
            week_summary['reject_rate'] = round(((week_summary['rejects'] + week_summary['cutbacks']) / total_production * 100), 2)
        else:
            week_summary['reject_rate'] = 0
        
        summary_data['weekly_data'].append(week_summary)
    
    # Calculate monthly summary totals
    for week_summary in summary_data['weekly_data']:
        summary_data['monthly_totals']['total_booked_hours_header'] += week_summary['booked_hours_header']
        summary_data['monthly_totals']['total_working_hours'] += week_summary['working_hours']
        summary_data['monthly_totals']['total_planned_production'] += week_summary['planned_production']
        summary_data['monthly_totals']['total_output_qty'] += week_summary['output_qty']
        summary_data['monthly_totals']['total_rejects'] += week_summary['rejects']
        summary_data['monthly_totals']['total_cutbacks'] += week_summary['cutbacks']
        summary_data['monthly_totals']['total_absorption_hours'] += week_summary['absorption_hours']
        summary_data['monthly_totals']['total_wait_material'] += week_summary['wait_material']
        summary_data['monthly_totals']['total_meetings'] += week_summary['meetings']
        summary_data['monthly_totals']['total_breakdown'] += week_summary['breakdown']
        summary_data['monthly_totals']['total_change_over'] += week_summary['change_over']
        summary_data['monthly_totals']['total_operating_hours'] += week_summary['operating_hours']
        summary_data['monthly_totals']['total_non_recorded_time'] += week_summary['non_recorded_time']
    
    oee_values = [w['oee'] for w in summary_data['weekly_data'] if w['oee'] > 0]
    reject_values = [w['reject_rate'] for w in summary_data['weekly_data'] if w['reject_rate'] >= 0]
    
    summary_data['monthly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['monthly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_weeks = len(weeks)
    summary_data['monthly_totals']['target_booked_hours_header'] = 105.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_working_hours'] = 105.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_output_qty'] = 85.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_oee'] = 85.0
    summary_data['monthly_totals']['target_reject_rate'] = 1.5
    
    # Calculate summary variances
    summary_data['monthly_totals']['variance_booked_hours_header'] = round(summary_data['monthly_totals']['total_booked_hours_header'] - summary_data['monthly_totals']['target_booked_hours_header'], 1)
    summary_data['monthly_totals']['variance_working_hours'] = round(summary_data['monthly_totals']['total_working_hours'] - summary_data['monthly_totals']['target_working_hours'], 1)
    summary_data['monthly_totals']['variance_output_qty'] = round(summary_data['monthly_totals']['total_output_qty'] - summary_data['monthly_totals']['target_output_qty'], 1)
    summary_data['monthly_totals']['variance_oee'] = round(summary_data['monthly_totals']['average_oee'] - summary_data['monthly_totals']['target_oee'], 1)
    summary_data['monthly_totals']['variance_reject_rate'] = round(summary_data['monthly_totals']['average_reject_rate'] - summary_data['monthly_totals']['target_reject_rate'], 1)
    
    # Calculate summary percentages
    summary_data['monthly_totals']['percent_booked_hours_header'] = round((summary_data['monthly_totals']['total_booked_hours_header'] / summary_data['monthly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['monthly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['monthly_totals']['percent_working_hours'] = round((summary_data['monthly_totals']['total_working_hours'] / summary_data['monthly_totals']['target_working_hours']) * 100, 1) if summary_data['monthly_totals']['target_working_hours'] > 0 else 0
    summary_data['monthly_totals']['percent_output_qty'] = round((summary_data['monthly_totals']['total_output_qty'] / summary_data['monthly_totals']['target_output_qty']) * 100, 1) if summary_data['monthly_totals']['target_output_qty'] > 0 else 0
    summary_data['monthly_totals']['percent_oee'] = round((summary_data['monthly_totals']['average_oee'] / summary_data['monthly_totals']['target_oee']) * 100, 1) if summary_data['monthly_totals']['target_oee'] > 0 else 0
    
    # Month name
    month_name = datetime(year, month, 1).strftime('%B %Y')
    
    context = {
        'month': month,
        'year': year,
        'month_name': month_name,
        'first_day': first_day,
        'last_day': last_day,
        'weeks': weeks,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'thread_report_oee_monthly'
    }
    
    return render(request, 'thread/report_oee_monthly.html', context)

@threading_report_access_required
def thread_report_oee_quarterly(request):
    """
    Quarterly OEE Report - Shows monthly summaries for each month in a quarter
    UPDATED: New OEE formula = ((Output - (Reject + Cutback)) × CT) / Booked Hours × 100%
    """
    # Get quarter and year from request or default to current quarter
    quarter = request.GET.get('quarter')
    year = request.GET.get('year')
    
    if not quarter or not year:
        today = datetime.now().date()
        quarter = ((today.month - 1) // 3) + 1
        year = today.year
    else:
        quarter = int(quarter)
        year = int(year)
    
    # Calculate first and last month of quarter
    first_month = (quarter - 1) * 3 + 1
    last_month = first_month + 2
    
    # Get first and last day of the quarter
    first_day = datetime(year, first_month, 1).date()
    if last_month == 12:
        last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        last_day = datetime(year, last_month + 1, 1).date() - timedelta(days=1)
    
    # Build months list
    months = []
    for month_num in range(first_month, last_month + 1):
        month_start = datetime(year, month_num, 1).date()
        if month_num == 12:
            month_end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(year, month_num + 1, 1).date() - timedelta(days=1)
        
        months.append({
            'month_number': month_num,
            'month_name': datetime(year, month_num, 1).strftime('%B'),
            'start_date': month_start,
            'end_date': month_end
        })
    
    # Get all machines
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    machines = Machine.objects.filter(process_type=threading_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'monthly_data': [],
            'quarterly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_absorption_hours': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each month
        for month in months:
            # Get thread headers for this month
            thread_headers = ThreadHeader.objects.filter(
                machine=machine,
                date__range=[month['start_date'], month['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize monthly data
            monthly_summary = {
                'month_number': month['month_number'],
                'month_name': month['month_name'],
                'start_date': month['start_date'],
                'end_date': month['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'absorption_hours': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
                'total_cycle_time_output': 0,  # For OEE calculation
            }
            
            # Calculate totals from headers
            for header in thread_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    monthly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            monthly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        monthly_summary['output_qty'] += float(detail.output)
                    
                    # For OEE: accumulate (Output × CT)
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            monthly_summary['total_cycle_time_output'] += (output * ct)
                        except (ValueError, TypeError):
                            pass
                    
                    # Planned production
                    if detail.ct and monthly_summary['booked_hours_header'] > 0:
                        try:
                            ct = float(detail.ct)
                            if ct > 0:
                                monthly_summary['planned_production'] += monthly_summary['booked_hours_header'] / ct
                        except (ValueError, TypeError):
                            pass
                    
                    # Absorption hours
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            process_rate = 0
                            if machine.process_type and machine.process_type.rate:
                                process_rate = float(machine.process_type.rate)
                            monthly_summary['absorption_hours'] += process_rate * (ct * output)
                        except (ValueError, TypeError):
                            pass
                
                # Reason stops
                reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    monthly_summary['rejects'] += float(reason_stops.reject or 0)
                    monthly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    monthly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    monthly_summary['change_over'] += float(reason_stops.change_over or 0)
            
            # Calculate non-recorded time
            monthly_summary['non_recorded_time'] = (
                monthly_summary['wait_material'] + 
                monthly_summary['meetings'] + 
                monthly_summary['breakdown'] + 
                monthly_summary['change_over']
            )
            
            # Calculate operating hours
            monthly_summary['operating_hours'] = max(0, monthly_summary['working_hours'] - monthly_summary['non_recorded_time'])
            
            # ========================================
            # NEW OEE CALCULATION FOR MONTHLY AGGREGATE
            # OEE = ((Output - Reject - Cutback) × CT) / Booked Hours × 100%
            # ========================================
            if monthly_summary['booked_hours_header'] > 0 and monthly_summary['output_qty'] > 0:
                good_output = monthly_summary['output_qty'] - monthly_summary['rejects'] - monthly_summary['cutbacks']
                good_output = max(0, good_output)
                
                # Calculate good output ratio
                good_output_ratio = good_output / monthly_summary['output_qty'] if monthly_summary['output_qty'] > 0 else 0
                
                # Apply ratio to total_cycle_time_output
                good_cycle_time_output = monthly_summary['total_cycle_time_output'] * good_output_ratio
                
                if monthly_summary['booked_hours_header'] > 0:
                    oee_value = (good_cycle_time_output / monthly_summary['booked_hours_header']) * 100
                    oee_value = max(0, min(oee_value, 100))  # Cap between 0-100%
                else:
                    oee_value = 0
                
                monthly_summary['oee'] = round(oee_value, 2)
            else:
                monthly_summary['oee'] = 0
            
            # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = monthly_summary['output_qty'] + monthly_summary['rejects'] + monthly_summary['cutbacks']
            if total_production > 0:
                monthly_summary['reject_rate'] = round(((monthly_summary['rejects'] + monthly_summary['cutbacks']) / total_production * 100), 2)
            else:
                monthly_summary['reject_rate'] = 0
            
            # Add to machine's monthly data
            machine_info['monthly_data'].append(monthly_summary)
            
            # Accumulate quarterly totals
            machine_info['quarterly_totals']['total_booked_hours_header'] += monthly_summary['booked_hours_header']
            machine_info['quarterly_totals']['total_working_hours'] += monthly_summary['working_hours']
            machine_info['quarterly_totals']['total_planned_production'] += monthly_summary['planned_production']
            machine_info['quarterly_totals']['total_output_qty'] += monthly_summary['output_qty']
            machine_info['quarterly_totals']['total_rejects'] += monthly_summary['rejects']
            machine_info['quarterly_totals']['total_cutbacks'] += monthly_summary['cutbacks']
            machine_info['quarterly_totals']['total_absorption_hours'] += monthly_summary['absorption_hours']
            machine_info['quarterly_totals']['total_wait_material'] += monthly_summary['wait_material']
            machine_info['quarterly_totals']['total_meetings'] += monthly_summary['meetings']
            machine_info['quarterly_totals']['total_breakdown'] += monthly_summary['breakdown']
            machine_info['quarterly_totals']['total_change_over'] += monthly_summary['change_over']
            machine_info['quarterly_totals']['total_operating_hours'] += monthly_summary['operating_hours']
            machine_info['quarterly_totals']['total_non_recorded_time'] += monthly_summary['non_recorded_time']
            
            if monthly_summary['oee'] > 0:
                total_oee_sum += monthly_summary['oee']
                total_oee_count += 1
            
            if monthly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += monthly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate quarterly averages
        machine_info['quarterly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['quarterly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply monthly targets by 3 months)
        num_months = len(months)
        machine_info['quarterly_totals']['target_booked_hours_header'] = 420.0 * num_months  # 105 * 4 weeks
        machine_info['quarterly_totals']['target_working_hours'] = 420.0 * num_months
        machine_info['quarterly_totals']['target_output_qty'] = 340.0 * num_months  # 85 * 4 weeks
        machine_info['quarterly_totals']['target_oee'] = 85.0
        machine_info['quarterly_totals']['target_reject_rate'] = 1.5
        
        # Calculate variances
        machine_info['quarterly_totals']['variance_booked_hours_header'] = round(machine_info['quarterly_totals']['total_booked_hours_header'] - machine_info['quarterly_totals']['target_booked_hours_header'], 1)
        machine_info['quarterly_totals']['variance_working_hours'] = round(machine_info['quarterly_totals']['total_working_hours'] - machine_info['quarterly_totals']['target_working_hours'], 1)
        machine_info['quarterly_totals']['variance_output_qty'] = round(machine_info['quarterly_totals']['total_output_qty'] - machine_info['quarterly_totals']['target_output_qty'], 1)
        machine_info['quarterly_totals']['variance_oee'] = round(machine_info['quarterly_totals']['average_oee'] - machine_info['quarterly_totals']['target_oee'], 1)
        machine_info['quarterly_totals']['variance_reject_rate'] = round(machine_info['quarterly_totals']['average_reject_rate'] - machine_info['quarterly_totals']['target_reject_rate'], 1)
        
        # Calculate percentages
        machine_info['quarterly_totals']['percent_booked_hours_header'] = round((machine_info['quarterly_totals']['total_booked_hours_header'] / machine_info['quarterly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['quarterly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['quarterly_totals']['percent_working_hours'] = round((machine_info['quarterly_totals']['total_working_hours'] / machine_info['quarterly_totals']['target_working_hours']) * 100, 1) if machine_info['quarterly_totals']['target_working_hours'] > 0 else 0
        machine_info['quarterly_totals']['percent_output_qty'] = round((machine_info['quarterly_totals']['total_output_qty'] / machine_info['quarterly_totals']['target_output_qty']) * 100, 1) if machine_info['quarterly_totals']['target_output_qty'] > 0 else 0
        machine_info['quarterly_totals']['percent_oee'] = round((machine_info['quarterly_totals']['average_oee'] / machine_info['quarterly_totals']['target_oee']) * 100, 1) if machine_info['quarterly_totals']['target_oee'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'monthly_data': [],
        'quarterly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_absorption_hours': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate monthly summaries across all machines
    for month in months:
        month_summary = {
            'month_number': month['month_number'],
            'month_name': month['month_name'],
            'start_date': month['start_date'],
            'end_date': month['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'absorption_hours': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for monthly_data in machine_info['monthly_data']:
                if monthly_data['month_number'] == month['month_number']:
                    month_summary['booked_hours_header'] += monthly_data['booked_hours_header']
                    month_summary['working_hours'] += monthly_data['working_hours']
                    month_summary['planned_production'] += monthly_data['planned_production']
                    month_summary['output_qty'] += monthly_data['output_qty']
                    month_summary['rejects'] += monthly_data['rejects']
                    month_summary['cutbacks'] += monthly_data['cutbacks']
                    month_summary['absorption_hours'] += monthly_data['absorption_hours']
                    month_summary['wait_material'] += monthly_data['wait_material']
                    month_summary['meetings'] += monthly_data['meetings']
                    month_summary['breakdown'] += monthly_data['breakdown']
                    month_summary['change_over'] += monthly_data['change_over']
                    month_summary['operating_hours'] += monthly_data['operating_hours']
                    month_summary['non_recorded_time'] += monthly_data['non_recorded_time']
                    
                    if monthly_data['oee'] > 0:
                        oee_values.append(monthly_data['oee'])
                    if monthly_data['reject_rate'] >= 0:
                        reject_rates.append(monthly_data['reject_rate'])
        
        month_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # Calculate reject rate for summary
        total_production = month_summary['output_qty'] + month_summary['rejects'] + month_summary['cutbacks']
        if total_production > 0:
            month_summary['reject_rate'] = round(((month_summary['rejects'] + month_summary['cutbacks']) / total_production * 100), 2)
        else:
            month_summary['reject_rate'] = 0
        
        summary_data['monthly_data'].append(month_summary)
    
    # Calculate quarterly summary totals
    for month_summary in summary_data['monthly_data']:
        summary_data['quarterly_totals']['total_booked_hours_header'] += month_summary['booked_hours_header']
        summary_data['quarterly_totals']['total_working_hours'] += month_summary['working_hours']
        summary_data['quarterly_totals']['total_planned_production'] += month_summary['planned_production']
        summary_data['quarterly_totals']['total_output_qty'] += month_summary['output_qty']
        summary_data['quarterly_totals']['total_rejects'] += month_summary['rejects']
        summary_data['quarterly_totals']['total_cutbacks'] += month_summary['cutbacks']
        summary_data['quarterly_totals']['total_absorption_hours'] += month_summary['absorption_hours']
        summary_data['quarterly_totals']['total_wait_material'] += month_summary['wait_material']
        summary_data['quarterly_totals']['total_meetings'] += month_summary['meetings']
        summary_data['quarterly_totals']['total_breakdown'] += month_summary['breakdown']
        summary_data['quarterly_totals']['total_change_over'] += month_summary['change_over']
        summary_data['quarterly_totals']['total_operating_hours'] += month_summary['operating_hours']
        summary_data['quarterly_totals']['total_non_recorded_time'] += month_summary['non_recorded_time']
    
    oee_values = [m['oee'] for m in summary_data['monthly_data'] if m['oee'] > 0]
    reject_values = [m['reject_rate'] for m in summary_data['monthly_data'] if m['reject_rate'] >= 0]
    
    summary_data['quarterly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['quarterly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_months = len(months)
    summary_data['quarterly_totals']['target_booked_hours_header'] = 420.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_working_hours'] = 420.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_output_qty'] = 340.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_oee'] = 85.0
    summary_data['quarterly_totals']['target_reject_rate'] = 1.5
    
    # Calculate summary variances
    summary_data['quarterly_totals']['variance_booked_hours_header'] = round(summary_data['quarterly_totals']['total_booked_hours_header'] - summary_data['quarterly_totals']['target_booked_hours_header'], 1)
    summary_data['quarterly_totals']['variance_working_hours'] = round(summary_data['quarterly_totals']['total_working_hours'] - summary_data['quarterly_totals']['target_working_hours'], 1)
    summary_data['quarterly_totals']['variance_output_qty'] = round(summary_data['quarterly_totals']['total_output_qty'] - summary_data['quarterly_totals']['target_output_qty'], 1)
    summary_data['quarterly_totals']['variance_oee'] = round(summary_data['quarterly_totals']['average_oee'] - summary_data['quarterly_totals']['target_oee'], 1)
    summary_data['quarterly_totals']['variance_reject_rate'] = round(summary_data['quarterly_totals']['average_reject_rate'] - summary_data['quarterly_totals']['target_reject_rate'], 1)
    
    # Calculate summary percentages
    summary_data['quarterly_totals']['percent_booked_hours_header'] = round((summary_data['quarterly_totals']['total_booked_hours_header'] / summary_data['quarterly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['quarterly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['quarterly_totals']['percent_working_hours'] = round((summary_data['quarterly_totals']['total_working_hours'] / summary_data['quarterly_totals']['target_working_hours']) * 100, 1) if summary_data['quarterly_totals']['target_working_hours'] > 0 else 0
    summary_data['quarterly_totals']['percent_output_qty'] = round((summary_data['quarterly_totals']['total_output_qty'] / summary_data['quarterly_totals']['target_output_qty']) * 100, 1) if summary_data['quarterly_totals']['target_output_qty'] > 0 else 0
    summary_data['quarterly_totals']['percent_oee'] = round((summary_data['quarterly_totals']['average_oee'] / summary_data['quarterly_totals']['target_oee']) * 100, 1) if summary_data['quarterly_totals']['target_oee'] > 0 else 0
    
    # Quarter name
    quarter_name = f"Q{quarter} {year}"
    
    context = {
        'quarter': quarter,
        'year': year,
        'quarter_name': quarter_name,
        'first_day': first_day,
        'last_day': last_day,
        'months': months,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'thread_report_oee_quarterly'
    }
    
    return render(request, 'thread/report_oee_quarterly.html', context)

@threading_report_access_required
def thread_report_oee_yearly(request):
    """
    Yearly OEE Report - Shows monthly summaries for each month in a year
    UPDATED: New OEE formula = ((Output - (Reject + Cutback)) × CT) / Booked Hours × 100%
    """
    # Get year from request or default to current year
    year = request.GET.get('year')
    
    if not year:
        today = datetime.now().date()
        year = today.year
    else:
        year = int(year)
    
    # Get first and last day of the year
    first_day = datetime(year, 1, 1).date()
    last_day = datetime(year, 12, 31).date()
    
    # Build months list (all 12 months)
    months = []
    for month_num in range(1, 13):
        month_start = datetime(year, month_num, 1).date()
        if month_num == 12:
            month_end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(year, month_num + 1, 1).date() - timedelta(days=1)
        
        months.append({
            'month_number': month_num,
            'month_name': datetime(year, month_num, 1).strftime('%b'),  # Short name: Jan, Feb, etc
            'month_full_name': datetime(year, month_num, 1).strftime('%B'),
            'start_date': month_start,
            'end_date': month_end
        })
    
    # Get all machines
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    machines = Machine.objects.filter(process_type=threading_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'monthly_data': [],
            'yearly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_absorption_hours': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each month
        for month in months:
            # Get thread headers for this month
            thread_headers = ThreadHeader.objects.filter(
                machine=machine,
                date__range=[month['start_date'], month['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize monthly data
            monthly_summary = {
                'month_number': month['month_number'],
                'month_name': month['month_name'],
                'month_full_name': month['month_full_name'],
                'start_date': month['start_date'],
                'end_date': month['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'absorption_hours': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
                'total_cycle_time_output': 0,  # For OEE calculation
            }
            
            # Calculate totals from headers
            for header in thread_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    monthly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            monthly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        monthly_summary['output_qty'] += float(detail.output)
                    
                    # For OEE: accumulate (Output × CT)
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            monthly_summary['total_cycle_time_output'] += (output * ct)
                        except (ValueError, TypeError):
                            pass
                    
                    # Planned production
                    if detail.ct and monthly_summary['booked_hours_header'] > 0:
                        try:
                            ct = float(detail.ct)
                            if ct > 0:
                                monthly_summary['planned_production'] += monthly_summary['booked_hours_header'] / ct
                        except (ValueError, TypeError):
                            pass
                    
                    # Absorption hours
                    if detail.ct and detail.output:
                        try:
                            ct = float(detail.ct)
                            output = float(detail.output)
                            process_rate = 0
                            if machine.process_type and machine.process_type.rate:
                                process_rate = float(machine.process_type.rate)
                            monthly_summary['absorption_hours'] += process_rate * (ct * output)
                        except (ValueError, TypeError):
                            pass
                
                # Reason stops
                reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    monthly_summary['rejects'] += float(reason_stops.reject or 0)
                    monthly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    monthly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    monthly_summary['change_over'] += float(reason_stops.change_over or 0)
            
            # Calculate non-recorded time
            monthly_summary['non_recorded_time'] = (
                monthly_summary['wait_material'] + 
                monthly_summary['meetings'] + 
                monthly_summary['breakdown'] + 
                monthly_summary['change_over']
            )
            
            # Calculate operating hours
            monthly_summary['operating_hours'] = max(0, monthly_summary['working_hours'] - monthly_summary['non_recorded_time'])
            
            # ========================================
            # NEW OEE CALCULATION FOR MONTHLY AGGREGATE
            # OEE = ((Output - Reject - Cutback) × CT) / Booked Hours × 100%
            # ========================================
            if monthly_summary['booked_hours_header'] > 0 and monthly_summary['output_qty'] > 0:
                good_output = monthly_summary['output_qty'] - monthly_summary['rejects'] - monthly_summary['cutbacks']
                good_output = max(0, good_output)
                
                # Calculate good output ratio
                good_output_ratio = good_output / monthly_summary['output_qty'] if monthly_summary['output_qty'] > 0 else 0
                
                # Apply ratio to total_cycle_time_output
                good_cycle_time_output = monthly_summary['total_cycle_time_output'] * good_output_ratio
                
                if monthly_summary['booked_hours_header'] > 0:
                    oee_value = (good_cycle_time_output / monthly_summary['booked_hours_header']) * 100
                    oee_value = max(0, min(oee_value, 100))  # Cap between 0-100%
                else:
                    oee_value = 0
                
                monthly_summary['oee'] = round(oee_value, 2)
            else:
                monthly_summary['oee'] = 0
            
            # Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = monthly_summary['output_qty'] + monthly_summary['rejects'] + monthly_summary['cutbacks']
            if total_production > 0:
                monthly_summary['reject_rate'] = round(((monthly_summary['rejects'] + monthly_summary['cutbacks']) / total_production * 100), 2)
            else:
                monthly_summary['reject_rate'] = 0
            
            # Add to machine's monthly data
            machine_info['monthly_data'].append(monthly_summary)
            
            # Accumulate yearly totals
            machine_info['yearly_totals']['total_booked_hours_header'] += monthly_summary['booked_hours_header']
            machine_info['yearly_totals']['total_working_hours'] += monthly_summary['working_hours']
            machine_info['yearly_totals']['total_planned_production'] += monthly_summary['planned_production']
            machine_info['yearly_totals']['total_output_qty'] += monthly_summary['output_qty']
            machine_info['yearly_totals']['total_rejects'] += monthly_summary['rejects']
            machine_info['yearly_totals']['total_cutbacks'] += monthly_summary['cutbacks']
            machine_info['yearly_totals']['total_absorption_hours'] += monthly_summary['absorption_hours']
            machine_info['yearly_totals']['total_wait_material'] += monthly_summary['wait_material']
            machine_info['yearly_totals']['total_meetings'] += monthly_summary['meetings']
            machine_info['yearly_totals']['total_breakdown'] += monthly_summary['breakdown']
            machine_info['yearly_totals']['total_change_over'] += monthly_summary['change_over']
            machine_info['yearly_totals']['total_operating_hours'] += monthly_summary['operating_hours']
            machine_info['yearly_totals']['total_non_recorded_time'] += monthly_summary['non_recorded_time']
            
            if monthly_summary['oee'] > 0:
                total_oee_sum += monthly_summary['oee']
                total_oee_count += 1
            
            if monthly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += monthly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate yearly averages
        machine_info['yearly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['yearly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply monthly targets by 12 months)
        num_months = 12
        machine_info['yearly_totals']['target_booked_hours_header'] = 420.0 * num_months  # 105 * 4 weeks * 12 months
        machine_info['yearly_totals']['target_working_hours'] = 420.0 * num_months
        machine_info['yearly_totals']['target_output_qty'] = 340.0 * num_months  # 85 * 4 weeks * 12 months
        machine_info['yearly_totals']['target_oee'] = 85.0
        machine_info['yearly_totals']['target_reject_rate'] = 1.5
        
        # Calculate variances
        machine_info['yearly_totals']['variance_booked_hours_header'] = round(machine_info['yearly_totals']['total_booked_hours_header'] - machine_info['yearly_totals']['target_booked_hours_header'], 1)
        machine_info['yearly_totals']['variance_working_hours'] = round(machine_info['yearly_totals']['total_working_hours'] - machine_info['yearly_totals']['target_working_hours'], 1)
        machine_info['yearly_totals']['variance_output_qty'] = round(machine_info['yearly_totals']['total_output_qty'] - machine_info['yearly_totals']['target_output_qty'], 1)
        machine_info['yearly_totals']['variance_oee'] = round(machine_info['yearly_totals']['average_oee'] - machine_info['yearly_totals']['target_oee'], 1)
        machine_info['yearly_totals']['variance_reject_rate'] = round(machine_info['yearly_totals']['average_reject_rate'] - machine_info['yearly_totals']['target_reject_rate'], 1)
        
        # Calculate percentages
        machine_info['yearly_totals']['percent_booked_hours_header'] = round((machine_info['yearly_totals']['total_booked_hours_header'] / machine_info['yearly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['yearly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['yearly_totals']['percent_working_hours'] = round((machine_info['yearly_totals']['total_working_hours'] / machine_info['yearly_totals']['target_working_hours']) * 100, 1) if machine_info['yearly_totals']['target_working_hours'] > 0 else 0
        machine_info['yearly_totals']['percent_output_qty'] = round((machine_info['yearly_totals']['total_output_qty'] / machine_info['yearly_totals']['target_output_qty']) * 100, 1) if machine_info['yearly_totals']['target_output_qty'] > 0 else 0
        machine_info['yearly_totals']['percent_oee'] = round((machine_info['yearly_totals']['average_oee'] / machine_info['yearly_totals']['target_oee']) * 100, 1) if machine_info['yearly_totals']['target_oee'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'monthly_data': [],
        'yearly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_absorption_hours': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate monthly summaries across all machines
    for month in months:
        month_summary = {
            'month_number': month['month_number'],
            'month_name': month['month_name'],
            'month_full_name': month['month_full_name'],
            'start_date': month['start_date'],
            'end_date': month['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'absorption_hours': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for monthly_data in machine_info['monthly_data']:
                if monthly_data['month_number'] == month['month_number']:
                    month_summary['booked_hours_header'] += monthly_data['booked_hours_header']
                    month_summary['working_hours'] += monthly_data['working_hours']
                    month_summary['planned_production'] += monthly_data['planned_production']
                    month_summary['output_qty'] += monthly_data['output_qty']
                    month_summary['rejects'] += monthly_data['rejects']
                    month_summary['cutbacks'] += monthly_data['cutbacks']
                    month_summary['absorption_hours'] += monthly_data['absorption_hours']
                    month_summary['wait_material'] += monthly_data['wait_material']
                    month_summary['meetings'] += monthly_data['meetings']
                    month_summary['breakdown'] += monthly_data['breakdown']
                    month_summary['change_over'] += monthly_data['change_over']
                    month_summary['operating_hours'] += monthly_data['operating_hours']
                    month_summary['non_recorded_time'] += monthly_data['non_recorded_time']
                    
                    if monthly_data['oee'] > 0:
                        oee_values.append(monthly_data['oee'])
                    if monthly_data['reject_rate'] >= 0:
                        reject_rates.append(monthly_data['reject_rate'])
        
        month_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # Calculate reject rate for summary
        total_production = month_summary['output_qty'] + month_summary['rejects'] + month_summary['cutbacks']
        if total_production > 0:
            month_summary['reject_rate'] = round(((month_summary['rejects'] + month_summary['cutbacks']) / total_production * 100), 2)
        else:
            month_summary['reject_rate'] = 0
        
        summary_data['monthly_data'].append(month_summary)
    
    # Calculate yearly summary totals
    for month_summary in summary_data['monthly_data']:
        summary_data['yearly_totals']['total_booked_hours_header'] += month_summary['booked_hours_header']
        summary_data['yearly_totals']['total_working_hours'] += month_summary['working_hours']
        summary_data['yearly_totals']['total_planned_production'] += month_summary['planned_production']
        summary_data['yearly_totals']['total_output_qty'] += month_summary['output_qty']
        summary_data['yearly_totals']['total_rejects'] += month_summary['rejects']
        summary_data['yearly_totals']['total_cutbacks'] += month_summary['cutbacks']
        summary_data['yearly_totals']['total_absorption_hours'] += month_summary['absorption_hours']
        summary_data['yearly_totals']['total_wait_material'] += month_summary['wait_material']
        summary_data['yearly_totals']['total_meetings'] += month_summary['meetings']
        summary_data['yearly_totals']['total_breakdown'] += month_summary['breakdown']
        summary_data['yearly_totals']['total_change_over'] += month_summary['change_over']
        summary_data['yearly_totals']['total_operating_hours'] += month_summary['operating_hours']
        summary_data['yearly_totals']['total_non_recorded_time'] += month_summary['non_recorded_time']
    
    oee_values = [m['oee'] for m in summary_data['monthly_data'] if m['oee'] > 0]
    reject_values = [m['reject_rate'] for m in summary_data['monthly_data'] if m['reject_rate'] >= 0]
    
    summary_data['yearly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['yearly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_months = 12
    summary_data['yearly_totals']['target_booked_hours_header'] = 420.0 * num_months * num_machines
    summary_data['yearly_totals']['target_working_hours'] = 420.0 * num_months * num_machines
    summary_data['yearly_totals']['target_output_qty'] = 340.0 * num_months * num_machines
    summary_data['yearly_totals']['target_oee'] = 85.0
    summary_data['yearly_totals']['target_reject_rate'] = 1.5
    
    # Calculate summary variances
    summary_data['yearly_totals']['variance_booked_hours_header'] = round(summary_data['yearly_totals']['total_booked_hours_header'] - summary_data['yearly_totals']['target_booked_hours_header'], 1)
    summary_data['yearly_totals']['variance_working_hours'] = round(summary_data['yearly_totals']['total_working_hours'] - summary_data['yearly_totals']['target_working_hours'], 1)
    summary_data['yearly_totals']['variance_output_qty'] = round(summary_data['yearly_totals']['total_output_qty'] - summary_data['yearly_totals']['target_output_qty'], 1)
    summary_data['yearly_totals']['variance_oee'] = round(summary_data['yearly_totals']['average_oee'] - summary_data['yearly_totals']['target_oee'], 1)
    summary_data['yearly_totals']['variance_reject_rate'] = round(summary_data['yearly_totals']['average_reject_rate'] - summary_data['yearly_totals']['target_reject_rate'], 1)
    
    # Calculate summary percentages
    summary_data['yearly_totals']['percent_booked_hours_header'] = round((summary_data['yearly_totals']['total_booked_hours_header'] / summary_data['yearly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['yearly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['yearly_totals']['percent_working_hours'] = round((summary_data['yearly_totals']['total_working_hours'] / summary_data['yearly_totals']['target_working_hours']) * 100, 1) if summary_data['yearly_totals']['target_working_hours'] > 0 else 0
    summary_data['yearly_totals']['percent_output_qty'] = round((summary_data['yearly_totals']['total_output_qty'] / summary_data['yearly_totals']['target_output_qty']) * 100, 1) if summary_data['yearly_totals']['target_output_qty'] > 0 else 0
    summary_data['yearly_totals']['percent_oee'] = round((summary_data['yearly_totals']['average_oee'] / summary_data['yearly_totals']['target_oee']) * 100, 1) if summary_data['yearly_totals']['target_oee'] > 0 else 0
    
    context = {
        'year': year,
        'first_day': first_day,
        'last_day': last_day,
        'months': months,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'thread_report_oee_yearly'
    }
    
    return render(request, 'thread/report_oee_yearly.html', context)

@welding_report_access_required
def weld_report_oee_monthly(request):
    """
    Monthly OEE Report for Welding - Shows weekly summaries for each week in a month
    """
    # Get month and year from request or default to current month
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    if not month or not year:
        today = datetime.now().date()
        month = today.month
        year = today.year
    else:
        month = int(month)
        year = int(year)
    
    # Get first and last day of the month
    first_day = datetime(year, month, 1).date()
    if month == 12:
        last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        last_day = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    # Find all Sunday-Saturday weeks in this month
    weeks = []
    current_date = first_day
    
    # Find first Sunday
    days_since_sunday = (current_date.weekday() + 1) % 7
    week_start = current_date - timedelta(days=days_since_sunday)
    
    while week_start <= last_day:
        week_end = week_start + timedelta(days=6)
        week_number = week_start.isocalendar()[1] + 1
        
        # Only include weeks that have at least one day in the current month
        if week_end >= first_day and week_start <= last_day:
            weeks.append({
                'week_number': week_number,
                'start_date': week_start,
                'end_date': week_end
            })
        
        week_start += timedelta(days=7)
    
    # Get all welding machines
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=welding_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'weekly_data': [],
            'monthly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each week
        for week in weeks:
            # Get weld headers for this week
            weld_headers = WeldHeader.objects.filter(
                machine=machine,
                date__range=[week['start_date'], week['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize weekly data
            weekly_summary = {
                'week_number': week['week_number'],
                'start_date': week['start_date'],
                'end_date': week['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
            }
            
            # Calculate totals from headers
            for header in weld_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    weekly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            weekly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        weekly_summary['output_qty'] += float(detail.output)
                    
                    # Planned production (using cycle time if available)
                    if detail.ct and weekly_summary['booked_hours_header'] > 0:
                        try:
                            ct = float(detail.ct)
                            if ct > 0:
                                weekly_summary['planned_production'] += weekly_summary['booked_hours_header'] / ct
                        except (ValueError, TypeError):
                            pass
                
                # Reason stops
                reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    weekly_summary['rejects'] += float(reason_stops.reject or 0)
                    weekly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    weekly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    weekly_summary['meetings'] += float(reason_stops.meeting or 0)
                    weekly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    weekly_summary['change_over'] += float(reason_stops.others or 0)
            
            # Calculate non-recorded time
            weekly_summary['non_recorded_time'] = (
                weekly_summary['wait_material'] + 
                weekly_summary['meetings'] + 
                weekly_summary['breakdown'] + 
                weekly_summary['change_over']
            )
            
            # Calculate operating hours
            weekly_summary['operating_hours'] = max(0, weekly_summary['working_hours'] - weekly_summary['non_recorded_time'])
            
            # Calculate OEE (simplified for weekly aggregate)
            if weekly_summary['booked_hours_header'] > 0 and weekly_summary['output_qty'] > 0:
                actual_hours = weekly_summary['booked_hours_header'] - weekly_summary['non_recorded_time']
                actual_hours = max(0, actual_hours)
                
                availability = (actual_hours / weekly_summary['booked_hours_header']) if weekly_summary['booked_hours_header'] > 0 else 0
                availability = min(availability, 1.0)
                
                # Use average performance estimation
                performance = 0.85  # Default performance assumption
                
                # UPDATED: Quality calculation with cutback included
                quality = ((weekly_summary['output_qty'] - weekly_summary['rejects'] - weekly_summary['cutbacks']) / weekly_summary['output_qty']) if weekly_summary['output_qty'] > 0 else 0
                quality = max(0, min(quality, 1.0))
                
                weekly_summary['oee'] = round(availability * performance * quality * 100, 2)
            
            # FIXED: Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = weekly_summary['output_qty'] + weekly_summary['rejects'] + weekly_summary['cutbacks']
            if total_production > 0:
                weekly_summary['reject_rate'] = round(((weekly_summary['rejects'] + weekly_summary['cutbacks']) / total_production * 100), 2)
            else:
                weekly_summary['reject_rate'] = 0
            
            # Add to machine's weekly data
            machine_info['weekly_data'].append(weekly_summary)
            
            # Accumulate monthly totals
            machine_info['monthly_totals']['total_booked_hours_header'] += weekly_summary['booked_hours_header']
            machine_info['monthly_totals']['total_working_hours'] += weekly_summary['working_hours']
            machine_info['monthly_totals']['total_planned_production'] += weekly_summary['planned_production']
            machine_info['monthly_totals']['total_output_qty'] += weekly_summary['output_qty']
            machine_info['monthly_totals']['total_rejects'] += weekly_summary['rejects']
            machine_info['monthly_totals']['total_cutbacks'] += weekly_summary['cutbacks']
            machine_info['monthly_totals']['total_wait_material'] += weekly_summary['wait_material']
            machine_info['monthly_totals']['total_meetings'] += weekly_summary['meetings']
            machine_info['monthly_totals']['total_breakdown'] += weekly_summary['breakdown']
            machine_info['monthly_totals']['total_change_over'] += weekly_summary['change_over']
            machine_info['monthly_totals']['total_operating_hours'] += weekly_summary['operating_hours']
            machine_info['monthly_totals']['total_non_recorded_time'] += weekly_summary['non_recorded_time']
            
            if weekly_summary['oee'] > 0:
                total_oee_sum += weekly_summary['oee']
                total_oee_count += 1
            
            if weekly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += weekly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate monthly averages
        machine_info['monthly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['monthly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply weekly targets by number of weeks)
        num_weeks = len(weeks)
        machine_info['monthly_totals']['target_booked_hours_header'] = 105.0 * num_weeks
        machine_info['monthly_totals']['target_working_hours'] = 105.0 * num_weeks
        machine_info['monthly_totals']['target_output_qty'] = 85.0 * num_weeks
        machine_info['monthly_totals']['target_oee'] = 85.0
        machine_info['monthly_totals']['target_reject_rate'] = 1.5
        machine_info['monthly_totals']['target_wait_material'] = 1.7 * num_weeks
        machine_info['monthly_totals']['target_meetings'] = 0.8 * num_weeks
        machine_info['monthly_totals']['target_breakdown'] = 1.7 * num_weeks
        machine_info['monthly_totals']['target_change_over'] = 4.2 * num_weeks
        machine_info['monthly_totals']['target_operating_hours'] = 84.0 * num_weeks
        machine_info['monthly_totals']['target_non_recorded_time'] = 8.4 * num_weeks
        
        # Calculate variances
        machine_info['monthly_totals']['variance_booked_hours_header'] = round(machine_info['monthly_totals']['total_booked_hours_header'] - machine_info['monthly_totals']['target_booked_hours_header'], 1)
        machine_info['monthly_totals']['variance_working_hours'] = round(machine_info['monthly_totals']['total_working_hours'] - machine_info['monthly_totals']['target_working_hours'], 1)
        machine_info['monthly_totals']['variance_output_qty'] = round(machine_info['monthly_totals']['total_output_qty'] - machine_info['monthly_totals']['target_output_qty'], 1)
        machine_info['monthly_totals']['variance_oee'] = round(machine_info['monthly_totals']['average_oee'] - machine_info['monthly_totals']['target_oee'], 1)
        machine_info['monthly_totals']['variance_reject_rate'] = round(machine_info['monthly_totals']['average_reject_rate'] - machine_info['monthly_totals']['target_reject_rate'], 1)
        machine_info['monthly_totals']['variance_wait_material'] = round(machine_info['monthly_totals']['total_wait_material'] - machine_info['monthly_totals']['target_wait_material'], 1)
        machine_info['monthly_totals']['variance_meetings'] = round(machine_info['monthly_totals']['total_meetings'] - machine_info['monthly_totals']['target_meetings'], 1)
        machine_info['monthly_totals']['variance_breakdown'] = round(machine_info['monthly_totals']['total_breakdown'] - machine_info['monthly_totals']['target_breakdown'], 1)
        machine_info['monthly_totals']['variance_change_over'] = round(machine_info['monthly_totals']['total_change_over'] - machine_info['monthly_totals']['target_change_over'], 1)
        machine_info['monthly_totals']['variance_operating_hours'] = round(machine_info['monthly_totals']['total_operating_hours'] - machine_info['monthly_totals']['target_operating_hours'], 1)
        machine_info['monthly_totals']['variance_non_recorded_time'] = round(machine_info['monthly_totals']['total_non_recorded_time'] - machine_info['monthly_totals']['target_non_recorded_time'], 1)
        
        # Calculate percentages
        machine_info['monthly_totals']['percent_booked_hours_header'] = round((machine_info['monthly_totals']['total_booked_hours_header'] / machine_info['monthly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['monthly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['monthly_totals']['percent_working_hours'] = round((machine_info['monthly_totals']['total_working_hours'] / machine_info['monthly_totals']['target_working_hours']) * 100, 1) if machine_info['monthly_totals']['target_working_hours'] > 0 else 0
        machine_info['monthly_totals']['percent_output_qty'] = round((machine_info['monthly_totals']['total_output_qty'] / machine_info['monthly_totals']['target_output_qty']) * 100, 1) if machine_info['monthly_totals']['target_output_qty'] > 0 else 0
        machine_info['monthly_totals']['percent_oee'] = round((machine_info['monthly_totals']['average_oee'] / machine_info['monthly_totals']['target_oee']) * 100, 1) if machine_info['monthly_totals']['target_oee'] > 0 else 0
        machine_info['monthly_totals']['percent_wait_material'] = round((machine_info['monthly_totals']['total_wait_material'] / machine_info['monthly_totals']['target_wait_material']) * 100, 1) if machine_info['monthly_totals']['target_wait_material'] > 0 else 0
        machine_info['monthly_totals']['percent_meetings'] = round((machine_info['monthly_totals']['total_meetings'] / machine_info['monthly_totals']['target_meetings']) * 100, 1) if machine_info['monthly_totals']['target_meetings'] > 0 else 0
        machine_info['monthly_totals']['percent_breakdown'] = round((machine_info['monthly_totals']['total_breakdown'] / machine_info['monthly_totals']['target_breakdown']) * 100, 1) if machine_info['monthly_totals']['target_breakdown'] > 0 else 0
        machine_info['monthly_totals']['percent_change_over'] = round((machine_info['monthly_totals']['total_change_over'] / machine_info['monthly_totals']['target_change_over']) * 100, 1) if machine_info['monthly_totals']['target_change_over'] > 0 else 0
        machine_info['monthly_totals']['percent_operating_hours'] = round((machine_info['monthly_totals']['total_operating_hours'] / machine_info['monthly_totals']['target_operating_hours']) * 100, 1) if machine_info['monthly_totals']['target_operating_hours'] > 0 else 0
        machine_info['monthly_totals']['percent_non_recorded_time'] = round((machine_info['monthly_totals']['total_non_recorded_time'] / machine_info['monthly_totals']['target_non_recorded_time']) * 100, 1) if machine_info['monthly_totals']['target_non_recorded_time'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'weekly_data': [],
        'monthly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate weekly summaries across all machines
    for week in weeks:
        week_summary = {
            'week_number': week['week_number'],
            'start_date': week['start_date'],
            'end_date': week['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for weekly_data in machine_info['weekly_data']:
                if weekly_data['week_number'] == week['week_number']:
                    week_summary['booked_hours_header'] += weekly_data['booked_hours_header']
                    week_summary['working_hours'] += weekly_data['working_hours']
                    week_summary['planned_production'] += weekly_data['planned_production']
                    week_summary['output_qty'] += weekly_data['output_qty']
                    week_summary['rejects'] += weekly_data['rejects']
                    week_summary['cutbacks'] += weekly_data['cutbacks']
                    week_summary['wait_material'] += weekly_data['wait_material']
                    week_summary['meetings'] += weekly_data['meetings']
                    week_summary['breakdown'] += weekly_data['breakdown']
                    week_summary['change_over'] += weekly_data['change_over']
                    week_summary['operating_hours'] += weekly_data['operating_hours']
                    week_summary['non_recorded_time'] += weekly_data['non_recorded_time']
                    
                    if weekly_data['oee'] > 0:
                        oee_values.append(weekly_data['oee'])
                    if weekly_data['reject_rate'] >= 0:
                        reject_rates.append(weekly_data['reject_rate'])
        
        week_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # FIXED: Calculate reject rate for summary with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
        total_production = week_summary['output_qty'] + week_summary['rejects'] + week_summary['cutbacks']
        if total_production > 0:
            week_summary['reject_rate'] = round(((week_summary['rejects'] + week_summary['cutbacks']) / total_production * 100), 2)
        else:
            week_summary['reject_rate'] = 0
        
        summary_data['weekly_data'].append(week_summary)
    
    # Calculate monthly summary totals
    for week_summary in summary_data['weekly_data']:
        summary_data['monthly_totals']['total_booked_hours_header'] += week_summary['booked_hours_header']
        summary_data['monthly_totals']['total_working_hours'] += week_summary['working_hours']
        summary_data['monthly_totals']['total_planned_production'] += week_summary['planned_production']
        summary_data['monthly_totals']['total_output_qty'] += week_summary['output_qty']
        summary_data['monthly_totals']['total_rejects'] += week_summary['rejects']
        summary_data['monthly_totals']['total_cutbacks'] += week_summary['cutbacks']
        summary_data['monthly_totals']['total_wait_material'] += week_summary['wait_material']
        summary_data['monthly_totals']['total_meetings'] += week_summary['meetings']
        summary_data['monthly_totals']['total_breakdown'] += week_summary['breakdown']
        summary_data['monthly_totals']['total_change_over'] += week_summary['change_over']
        summary_data['monthly_totals']['total_operating_hours'] += week_summary['operating_hours']
        summary_data['monthly_totals']['total_non_recorded_time'] += week_summary['non_recorded_time']
    
    oee_values = [w['oee'] for w in summary_data['weekly_data'] if w['oee'] > 0]
    reject_values = [w['reject_rate'] for w in summary_data['weekly_data'] if w['reject_rate'] >= 0]
    
    summary_data['monthly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['monthly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_weeks = len(weeks)
    summary_data['monthly_totals']['target_booked_hours_header'] = 105.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_working_hours'] = 105.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_output_qty'] = 85.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_oee'] = 85.0
    summary_data['monthly_totals']['target_reject_rate'] = 1.5
    summary_data['monthly_totals']['target_wait_material'] = 1.7 * num_weeks * num_machines
    summary_data['monthly_totals']['target_meetings'] = 0.8 * num_weeks * num_machines
    summary_data['monthly_totals']['target_breakdown'] = 1.7 * num_weeks * num_machines
    summary_data['monthly_totals']['target_change_over'] = 4.2 * num_weeks * num_machines
    summary_data['monthly_totals']['target_operating_hours'] = 84.0 * num_weeks * num_machines
    summary_data['monthly_totals']['target_non_recorded_time'] = 8.4 * num_weeks * num_machines
    
    # Calculate summary variances
    summary_data['monthly_totals']['variance_booked_hours_header'] = round(summary_data['monthly_totals']['total_booked_hours_header'] - summary_data['monthly_totals']['target_booked_hours_header'], 1)
    summary_data['monthly_totals']['variance_working_hours'] = round(summary_data['monthly_totals']['total_working_hours'] - summary_data['monthly_totals']['target_working_hours'], 1)
    summary_data['monthly_totals']['variance_output_qty'] = round(summary_data['monthly_totals']['total_output_qty'] - summary_data['monthly_totals']['target_output_qty'], 1)
    summary_data['monthly_totals']['variance_oee'] = round(summary_data['monthly_totals']['average_oee'] - summary_data['monthly_totals']['target_oee'], 1)
    summary_data['monthly_totals']['variance_reject_rate'] = round(summary_data['monthly_totals']['average_reject_rate'] - summary_data['monthly_totals']['target_reject_rate'], 1)
    summary_data['monthly_totals']['variance_wait_material'] = round(summary_data['monthly_totals']['total_wait_material'] - summary_data['monthly_totals']['target_wait_material'], 1)
    summary_data['monthly_totals']['variance_meetings'] = round(summary_data['monthly_totals']['total_meetings'] - summary_data['monthly_totals']['target_meetings'], 1)
    summary_data['monthly_totals']['variance_breakdown'] = round(summary_data['monthly_totals']['total_breakdown'] - summary_data['monthly_totals']['target_breakdown'], 1)
    summary_data['monthly_totals']['variance_change_over'] = round(summary_data['monthly_totals']['total_change_over'] - summary_data['monthly_totals']['target_change_over'], 1)
    summary_data['monthly_totals']['variance_operating_hours'] = round(summary_data['monthly_totals']['total_operating_hours'] - summary_data['monthly_totals']['target_operating_hours'], 1)
    summary_data['monthly_totals']['variance_non_recorded_time'] = round(summary_data['monthly_totals']['total_non_recorded_time'] - summary_data['monthly_totals']['target_non_recorded_time'], 1)
    
    # Calculate summary percentages
    summary_data['monthly_totals']['percent_booked_hours_header'] = round((summary_data['monthly_totals']['total_booked_hours_header'] / summary_data['monthly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['monthly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['monthly_totals']['percent_working_hours'] = round((summary_data['monthly_totals']['total_working_hours'] / summary_data['monthly_totals']['target_working_hours']) * 100, 1) if summary_data['monthly_totals']['target_working_hours'] > 0 else 0
    summary_data['monthly_totals']['percent_output_qty'] = round((summary_data['monthly_totals']['total_output_qty'] / summary_data['monthly_totals']['target_output_qty']) * 100, 1) if summary_data['monthly_totals']['target_output_qty'] > 0 else 0
    summary_data['monthly_totals']['percent_oee'] = round((summary_data['monthly_totals']['average_oee'] / summary_data['monthly_totals']['target_oee']) * 100, 1) if summary_data['monthly_totals']['target_oee'] > 0 else 0
    summary_data['monthly_totals']['percent_wait_material'] = round((summary_data['monthly_totals']['total_wait_material'] / summary_data['monthly_totals']['target_wait_material']) * 100, 1) if summary_data['monthly_totals']['target_wait_material'] > 0 else 0
    summary_data['monthly_totals']['percent_meetings'] = round((summary_data['monthly_totals']['total_meetings'] / summary_data['monthly_totals']['target_meetings']) * 100, 1) if summary_data['monthly_totals']['target_meetings'] > 0 else 0
    summary_data['monthly_totals']['percent_breakdown'] = round((summary_data['monthly_totals']['total_breakdown'] / summary_data['monthly_totals']['target_breakdown']) * 100, 1) if summary_data['monthly_totals']['target_breakdown'] > 0 else 0
    summary_data['monthly_totals']['percent_change_over'] = round((summary_data['monthly_totals']['total_change_over'] / summary_data['monthly_totals']['target_change_over']) * 100, 1) if summary_data['monthly_totals']['target_change_over'] > 0 else 0
    summary_data['monthly_totals']['percent_operating_hours'] = round((summary_data['monthly_totals']['total_operating_hours'] / summary_data['monthly_totals']['target_operating_hours']) * 100, 1) if summary_data['monthly_totals']['target_operating_hours'] > 0 else 0
    summary_data['monthly_totals']['percent_non_recorded_time'] = round((summary_data['monthly_totals']['total_non_recorded_time'] / summary_data['monthly_totals']['target_non_recorded_time']) * 100, 1) if summary_data['monthly_totals']['target_non_recorded_time'] > 0 else 0
    
    # Month name
    month_name = datetime(year, month, 1).strftime('%B %Y')
    
    context = {
        'month': month,
        'year': year,
        'month_name': month_name,
        'first_day': first_day,
        'last_day': last_day,
        'weeks': weeks,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'weld_report_oee_monthly'
    }
    
    return render(request, 'weld/report_oee_monthly.html', context)

@welding_report_access_required
def weld_report_oee_quarterly(request):
    """
    Quarterly OEE Report for Welding - Shows monthly summaries for each month in a quarter
    """
    # Get quarter and year from request or default to current quarter
    quarter = request.GET.get('quarter')
    year = request.GET.get('year')
    
    if not quarter or not year:
        today = datetime.now().date()
        quarter = ((today.month - 1) // 3) + 1
        year = today.year
    else:
        quarter = int(quarter)
        year = int(year)
    
    # Calculate first and last month of quarter
    first_month = (quarter - 1) * 3 + 1
    last_month = first_month + 2
    
    # Get first and last day of the quarter
    first_day = datetime(year, first_month, 1).date()
    if last_month == 12:
        last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        last_day = datetime(year, last_month + 1, 1).date() - timedelta(days=1)
    
    # Build months list
    months = []
    for month_num in range(first_month, last_month + 1):
        month_start = datetime(year, month_num, 1).date()
        if month_num == 12:
            month_end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(year, month_num + 1, 1).date() - timedelta(days=1)
        
        months.append({
            'month_number': month_num,
            'month_name': datetime(year, month_num, 1).strftime('%B'),
            'start_date': month_start,
            'end_date': month_end
        })
    
    # Get all welding machines
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=welding_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'monthly_data': [],
            'quarterly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each month
        for month in months:
            # Get weld headers for this month (only posted records)
            weld_headers = WeldHeader.objects.filter(
                machine=machine,
                date__range=[month['start_date'], month['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize monthly data
            monthly_summary = {
                'month_number': month['month_number'],
                'month_name': month['month_name'],
                'start_date': month['start_date'],
                'end_date': month['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
            }
            
            # Track cycle times and outputs for planned production calculation
            total_booked_hours = 0
            planned_hours_total = 0
            
            # Calculate totals from headers
            for header in weld_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    booked_hours_value = float(header.booked_hours.duration)
                    monthly_summary['booked_hours_header'] += booked_hours_value
                    total_booked_hours += booked_hours_value
                
                # Get details
                details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            monthly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        output_value = float(detail.output)
                        monthly_summary['output_qty'] += output_value
                        
                        # Calculate planned hours for this detail (Output × CT)
                        if detail.ct:
                            try:
                                cycle_time = float(detail.ct)
                                if cycle_time > 0:
                                    planned_hours_total += output_value * cycle_time
                            except (ValueError, TypeError):
                                pass
                
                # Reason stops
                reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    monthly_summary['rejects'] += float(reason_stops.reject or 0)
                    monthly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    monthly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    monthly_summary['change_over'] += float(reason_stops.others or 0)
            
            # Calculate planned production: if we have booked hours, distribute based on planned hours
            # Otherwise use simple division
            if total_booked_hours > 0 and planned_hours_total > 0:
                monthly_summary['planned_production'] = total_booked_hours / (planned_hours_total / monthly_summary['output_qty']) if monthly_summary['output_qty'] > 0 else 0
            else:
                monthly_summary['planned_production'] = monthly_summary['output_qty']
            
            # Calculate non-recorded time
            monthly_summary['non_recorded_time'] = (
                monthly_summary['wait_material'] + 
                monthly_summary['meetings'] + 
                monthly_summary['breakdown'] + 
                monthly_summary['change_over']
            )
            
            # Calculate operating hours
            monthly_summary['operating_hours'] = max(0, monthly_summary['working_hours'] - monthly_summary['non_recorded_time'])
            
            # Calculate OEE (simplified for monthly aggregate)
            if monthly_summary['booked_hours_header'] > 0 and monthly_summary['output_qty'] > 0:
                actual_hours = monthly_summary['booked_hours_header'] - monthly_summary['non_recorded_time']
                actual_hours = max(0, actual_hours)
                
                # 1. Availability = Actual Hours ÷ Booking Hours
                availability = (actual_hours / monthly_summary['booked_hours_header']) if monthly_summary['booked_hours_header'] > 0 else 0
                availability = min(availability, 1.0)
                
                # 2. Performance - use average performance estimation for monthly aggregate
                performance = 0.85  # Default performance assumption
                
                # 3. Quality = (Output - Reject) ÷ Output (TETAP SEPERTI SEMULA, TIDAK TERMASUK CUTBACK)
                quality = ((monthly_summary['output_qty'] - monthly_summary['rejects']) / monthly_summary['output_qty']) if monthly_summary['output_qty'] > 0 else 0
                quality = max(0, min(quality, 1.0))
                
                # OEE = Availability × Performance × Quality × 100%
                monthly_summary['oee'] = round(availability * performance * quality * 100, 2)
            
            # FIXED: Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = monthly_summary['output_qty'] + monthly_summary['rejects'] + monthly_summary['cutbacks']
            if total_production > 0:
                monthly_summary['reject_rate'] = round(((monthly_summary['rejects'] + monthly_summary['cutbacks']) / total_production * 100), 2)
            else:
                monthly_summary['reject_rate'] = 0
            
            # Add to machine's monthly data
            machine_info['monthly_data'].append(monthly_summary)
            
            # Accumulate quarterly totals
            machine_info['quarterly_totals']['total_booked_hours_header'] += monthly_summary['booked_hours_header']
            machine_info['quarterly_totals']['total_working_hours'] += monthly_summary['working_hours']
            machine_info['quarterly_totals']['total_planned_production'] += monthly_summary['planned_production']
            machine_info['quarterly_totals']['total_output_qty'] += monthly_summary['output_qty']
            machine_info['quarterly_totals']['total_rejects'] += monthly_summary['rejects']
            machine_info['quarterly_totals']['total_cutbacks'] += monthly_summary['cutbacks']
            machine_info['quarterly_totals']['total_wait_material'] += monthly_summary['wait_material']
            machine_info['quarterly_totals']['total_meetings'] += monthly_summary['meetings']
            machine_info['quarterly_totals']['total_breakdown'] += monthly_summary['breakdown']
            machine_info['quarterly_totals']['total_change_over'] += monthly_summary['change_over']
            machine_info['quarterly_totals']['total_operating_hours'] += monthly_summary['operating_hours']
            machine_info['quarterly_totals']['total_non_recorded_time'] += monthly_summary['non_recorded_time']
            
            if monthly_summary['oee'] > 0:
                total_oee_sum += monthly_summary['oee']
                total_oee_count += 1
            
            if monthly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += monthly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate quarterly averages
        machine_info['quarterly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['quarterly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply monthly targets by 3 months)
        num_months = len(months)
        machine_info['quarterly_totals']['target_booked_hours_header'] = 420.0 * num_months  # 105 * 4 weeks
        machine_info['quarterly_totals']['target_working_hours'] = 420.0 * num_months
        machine_info['quarterly_totals']['target_output_qty'] = 340.0 * num_months  # 85 * 4 weeks
        machine_info['quarterly_totals']['target_oee'] = 85.0
        machine_info['quarterly_totals']['target_reject_rate'] = 1.5
        
        # Calculate variances
        machine_info['quarterly_totals']['variance_booked_hours_header'] = round(machine_info['quarterly_totals']['total_booked_hours_header'] - machine_info['quarterly_totals']['target_booked_hours_header'], 1)
        machine_info['quarterly_totals']['variance_working_hours'] = round(machine_info['quarterly_totals']['total_working_hours'] - machine_info['quarterly_totals']['target_working_hours'], 1)
        machine_info['quarterly_totals']['variance_output_qty'] = round(machine_info['quarterly_totals']['total_output_qty'] - machine_info['quarterly_totals']['target_output_qty'], 1)
        machine_info['quarterly_totals']['variance_oee'] = round(machine_info['quarterly_totals']['average_oee'] - machine_info['quarterly_totals']['target_oee'], 1)
        machine_info['quarterly_totals']['variance_reject_rate'] = round(machine_info['quarterly_totals']['average_reject_rate'] - machine_info['quarterly_totals']['target_reject_rate'], 1)
        
        # Calculate percentages
        machine_info['quarterly_totals']['percent_booked_hours_header'] = round((machine_info['quarterly_totals']['total_booked_hours_header'] / machine_info['quarterly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['quarterly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['quarterly_totals']['percent_working_hours'] = round((machine_info['quarterly_totals']['total_working_hours'] / machine_info['quarterly_totals']['target_working_hours']) * 100, 1) if machine_info['quarterly_totals']['target_working_hours'] > 0 else 0
        machine_info['quarterly_totals']['percent_output_qty'] = round((machine_info['quarterly_totals']['total_output_qty'] / machine_info['quarterly_totals']['target_output_qty']) * 100, 1) if machine_info['quarterly_totals']['target_output_qty'] > 0 else 0
        machine_info['quarterly_totals']['percent_oee'] = round((machine_info['quarterly_totals']['average_oee'] / machine_info['quarterly_totals']['target_oee']) * 100, 1) if machine_info['quarterly_totals']['target_oee'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'monthly_data': [],
        'quarterly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate monthly summaries across all machines
    for month in months:
        month_summary = {
            'month_number': month['month_number'],
            'month_name': month['month_name'],
            'start_date': month['start_date'],
            'end_date': month['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for monthly_data in machine_info['monthly_data']:
                if monthly_data['month_number'] == month['month_number']:
                    month_summary['booked_hours_header'] += monthly_data['booked_hours_header']
                    month_summary['working_hours'] += monthly_data['working_hours']
                    month_summary['planned_production'] += monthly_data['planned_production']
                    month_summary['output_qty'] += monthly_data['output_qty']
                    month_summary['rejects'] += monthly_data['rejects']
                    month_summary['cutbacks'] += monthly_data['cutbacks']
                    month_summary['wait_material'] += monthly_data['wait_material']
                    month_summary['meetings'] += monthly_data['meetings']
                    month_summary['breakdown'] += monthly_data['breakdown']
                    month_summary['change_over'] += monthly_data['change_over']
                    month_summary['operating_hours'] += monthly_data['operating_hours']
                    month_summary['non_recorded_time'] += monthly_data['non_recorded_time']
                    
                    if monthly_data['oee'] > 0:
                        oee_values.append(monthly_data['oee'])
                    if monthly_data['reject_rate'] >= 0:
                        reject_rates.append(monthly_data['reject_rate'])
        
        month_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # FIXED: Calculate reject rate for summary with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
        total_production = month_summary['output_qty'] + month_summary['rejects'] + month_summary['cutbacks']
        if total_production > 0:
            month_summary['reject_rate'] = round(((month_summary['rejects'] + month_summary['cutbacks']) / total_production * 100), 2)
        else:
            month_summary['reject_rate'] = 0
        
        summary_data['monthly_data'].append(month_summary)
    
    # Calculate quarterly summary totals
    for month_summary in summary_data['monthly_data']:
        summary_data['quarterly_totals']['total_booked_hours_header'] += month_summary['booked_hours_header']
        summary_data['quarterly_totals']['total_working_hours'] += month_summary['working_hours']
        summary_data['quarterly_totals']['total_planned_production'] += month_summary['planned_production']
        summary_data['quarterly_totals']['total_output_qty'] += month_summary['output_qty']
        summary_data['quarterly_totals']['total_rejects'] += month_summary['rejects']
        summary_data['quarterly_totals']['total_cutbacks'] += month_summary['cutbacks']
        summary_data['quarterly_totals']['total_wait_material'] += month_summary['wait_material']
        summary_data['quarterly_totals']['total_meetings'] += month_summary['meetings']
        summary_data['quarterly_totals']['total_breakdown'] += month_summary['breakdown']
        summary_data['quarterly_totals']['total_change_over'] += month_summary['change_over']
        summary_data['quarterly_totals']['total_operating_hours'] += month_summary['operating_hours']
        summary_data['quarterly_totals']['total_non_recorded_time'] += month_summary['non_recorded_time']
    
    oee_values = [m['oee'] for m in summary_data['monthly_data'] if m['oee'] > 0]
    reject_values = [m['reject_rate'] for m in summary_data['monthly_data'] if m['reject_rate'] >= 0]
    
    summary_data['quarterly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['quarterly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_months = len(months)
    summary_data['quarterly_totals']['target_booked_hours_header'] = 420.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_working_hours'] = 420.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_output_qty'] = 340.0 * num_months * num_machines
    summary_data['quarterly_totals']['target_oee'] = 85.0
    summary_data['quarterly_totals']['target_reject_rate'] = 1.5
    
    # Calculate summary variances
    summary_data['quarterly_totals']['variance_booked_hours_header'] = round(summary_data['quarterly_totals']['total_booked_hours_header'] - summary_data['quarterly_totals']['target_booked_hours_header'], 1)
    summary_data['quarterly_totals']['variance_working_hours'] = round(summary_data['quarterly_totals']['total_working_hours'] - summary_data['quarterly_totals']['target_working_hours'], 1)
    summary_data['quarterly_totals']['variance_output_qty'] = round(summary_data['quarterly_totals']['total_output_qty'] - summary_data['quarterly_totals']['target_output_qty'], 1)
    summary_data['quarterly_totals']['variance_oee'] = round(summary_data['quarterly_totals']['average_oee'] - summary_data['quarterly_totals']['target_oee'], 1)
    summary_data['quarterly_totals']['variance_reject_rate'] = round(summary_data['quarterly_totals']['average_reject_rate'] - summary_data['quarterly_totals']['target_reject_rate'], 1)
    
    # Calculate summary percentages
    summary_data['quarterly_totals']['percent_booked_hours_header'] = round((summary_data['quarterly_totals']['total_booked_hours_header'] / summary_data['quarterly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['quarterly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['quarterly_totals']['percent_working_hours'] = round((summary_data['quarterly_totals']['total_working_hours'] / summary_data['quarterly_totals']['target_working_hours']) * 100, 1) if summary_data['quarterly_totals']['target_working_hours'] > 0 else 0
    summary_data['quarterly_totals']['percent_output_qty'] = round((summary_data['quarterly_totals']['total_output_qty'] / summary_data['quarterly_totals']['target_output_qty']) * 100, 1) if summary_data['quarterly_totals']['target_output_qty'] > 0 else 0
    summary_data['quarterly_totals']['percent_oee'] = round((summary_data['quarterly_totals']['average_oee'] / summary_data['quarterly_totals']['target_oee']) * 100, 1) if summary_data['quarterly_totals']['target_oee'] > 0 else 0
    
    # Quarter name
    quarter_name = f"Q{quarter} {year}"
    
    context = {
        'quarter': quarter,
        'year': year,
        'quarter_name': quarter_name,
        'first_day': first_day,
        'last_day': last_day,
        'months': months,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'weld_report_oee_quarterly'
    }
    
    return render(request, 'weld/report_oee_quarterly.html', context)

@welding_report_access_required
def weld_report_oee_yearly(request):
    """
    Yearly OEE Report for Welding - Shows monthly summaries for each month in a year
    """
    # Get year from request or default to current year
    year = request.GET.get('year')
    
    if not year:
        today = datetime.now().date()
        year = today.year
    else:
        year = int(year)
    
    # Get first and last day of the year
    first_day = datetime(year, 1, 1).date()
    last_day = datetime(year, 12, 31).date()
    
    # Build months list (all 12 months)
    months = []
    for month_num in range(1, 13):
        month_start = datetime(year, month_num, 1).date()
        if month_num == 12:
            month_end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(year, month_num + 1, 1).date() - timedelta(days=1)
        
        months.append({
            'month_number': month_num,
            'month_name': datetime(year, month_num, 1).strftime('%b'),  # Short name: Jan, Feb, etc
            'month_full_name': datetime(year, month_num, 1).strftime('%B'),
            'start_date': month_start,
            'end_date': month_end
        })
    
    # Get all welding machines
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=welding_process)
    
    # Process each machine
    machine_data = []
    
    for machine in machines:
        machine_info = {
            'machine': machine,
            'machine_name': machine.name,
            'monthly_data': [],
            'yearly_totals': {
                'total_output_qty': 0,
                'total_booked_hours_header': 0,
                'total_working_hours': 0,
                'total_planned_production': 0,
                'total_rejects': 0,
                'total_cutbacks': 0,
                'total_wait_material': 0,
                'total_meetings': 0,
                'total_breakdown': 0,
                'total_change_over': 0,
                'total_operating_hours': 0,
                'total_non_recorded_time': 0,
                'average_oee': 0,
                'average_reject_rate': 0,
            }
        }
        
        total_oee_sum = 0
        total_oee_count = 0
        total_reject_rate_sum = 0
        total_reject_rate_count = 0
        
        # Process each month
        for month in months:
            # Get weld headers for this month (only posted records)
            weld_headers = WeldHeader.objects.filter(
                machine=machine,
                date__range=[month['start_date'], month['end_date']],
                is_posted=True
            ).select_related('machine', 'operator', 'shift', 'booked_hours')
            
            # Initialize monthly data
            monthly_summary = {
                'month_number': month['month_number'],
                'month_name': month['month_name'],
                'month_full_name': month['month_full_name'],
                'start_date': month['start_date'],
                'end_date': month['end_date'],
                'booked_hours_header': 0,
                'working_hours': 0,
                'planned_production': 0,
                'output_qty': 0,
                'rejects': 0,
                'cutbacks': 0,
                'wait_material': 0,
                'meetings': 0,
                'breakdown': 0,
                'change_over': 0,
                'operating_hours': 0,
                'non_recorded_time': 0,
                'oee': 0,
                'reject_rate': 0,
            }
            
            # Track cycle times and outputs for planned production calculation
            total_booked_hours = 0
            planned_hours_total = 0
            
            # Calculate totals from headers
            for header in weld_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    booked_hours_value = float(header.booked_hours.duration)
                    monthly_summary['booked_hours_header'] += booked_hours_value
                    total_booked_hours += booked_hours_value
                
                # Get details
                details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
                
                for detail in details:
                    # Working hours
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours:
                            monthly_summary['working_hours'] += hours
                    
                    # Output
                    if detail.output:
                        output_value = float(detail.output)
                        monthly_summary['output_qty'] += output_value
                        
                        # Calculate planned hours for this detail (Output × CT)
                        if detail.ct:
                            try:
                                cycle_time = float(detail.ct)
                                if cycle_time > 0:
                                    planned_hours_total += output_value * cycle_time
                            except (ValueError, TypeError):
                                pass
                
                # Reason stops
                reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
                if reason_stops:
                    monthly_summary['rejects'] += float(reason_stops.reject or 0)
                    monthly_summary['cutbacks'] += float(reason_stops.cutback or 0)
                    monthly_summary['wait_material'] += float(reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(reason_stops.maintenance.duration if reason_stops.maintenance else 0)
                    monthly_summary['change_over'] += float(reason_stops.others or 0)
            
            # Calculate planned production
            if total_booked_hours > 0 and planned_hours_total > 0:
                monthly_summary['planned_production'] = total_booked_hours / (planned_hours_total / monthly_summary['output_qty']) if monthly_summary['output_qty'] > 0 else 0
            else:
                monthly_summary['planned_production'] = monthly_summary['output_qty']
            
            # Calculate non-recorded time
            monthly_summary['non_recorded_time'] = (
                monthly_summary['wait_material'] + 
                monthly_summary['meetings'] + 
                monthly_summary['breakdown'] + 
                monthly_summary['change_over']
            )
            
            # Calculate operating hours
            monthly_summary['operating_hours'] = max(0, monthly_summary['working_hours'] - monthly_summary['non_recorded_time'])
            
            # Calculate OEE
            if monthly_summary['booked_hours_header'] > 0 and monthly_summary['output_qty'] > 0:
                actual_hours = monthly_summary['booked_hours_header'] - monthly_summary['non_recorded_time']
                actual_hours = max(0, actual_hours)
                
                availability = (actual_hours / monthly_summary['booked_hours_header']) if monthly_summary['booked_hours_header'] > 0 else 0
                availability = min(availability, 1.0)
                
                # Use average performance estimation
                performance = 0.85  # Default performance assumption
                
                # Quality calculation (TETAP SEPERTI SEMULA - hanya reject, tidak termasuk cutback)
                quality = ((monthly_summary['output_qty'] - monthly_summary['rejects']) / monthly_summary['output_qty']) if monthly_summary['output_qty'] > 0 else 0
                quality = max(0, min(quality, 1.0))
                
                monthly_summary['oee'] = round(availability * performance * quality * 100, 2)
            
            # FIXED: Calculate reject rate with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
            total_production = monthly_summary['output_qty'] + monthly_summary['rejects'] + monthly_summary['cutbacks']
            if total_production > 0:
                monthly_summary['reject_rate'] = round(((monthly_summary['rejects'] + monthly_summary['cutbacks']) / total_production * 100), 2)
            else:
                monthly_summary['reject_rate'] = 0
            
            # Add to machine's monthly data
            machine_info['monthly_data'].append(monthly_summary)
            
            # Accumulate yearly totals
            machine_info['yearly_totals']['total_booked_hours_header'] += monthly_summary['booked_hours_header']
            machine_info['yearly_totals']['total_working_hours'] += monthly_summary['working_hours']
            machine_info['yearly_totals']['total_planned_production'] += monthly_summary['planned_production']
            machine_info['yearly_totals']['total_output_qty'] += monthly_summary['output_qty']
            machine_info['yearly_totals']['total_rejects'] += monthly_summary['rejects']
            machine_info['yearly_totals']['total_cutbacks'] += monthly_summary['cutbacks']
            machine_info['yearly_totals']['total_wait_material'] += monthly_summary['wait_material']
            machine_info['yearly_totals']['total_meetings'] += monthly_summary['meetings']
            machine_info['yearly_totals']['total_breakdown'] += monthly_summary['breakdown']
            machine_info['yearly_totals']['total_change_over'] += monthly_summary['change_over']
            machine_info['yearly_totals']['total_operating_hours'] += monthly_summary['operating_hours']
            machine_info['yearly_totals']['total_non_recorded_time'] += monthly_summary['non_recorded_time']
            
            if monthly_summary['oee'] > 0:
                total_oee_sum += monthly_summary['oee']
                total_oee_count += 1
            
            if monthly_summary['reject_rate'] >= 0:
                total_reject_rate_sum += monthly_summary['reject_rate']
                total_reject_rate_count += 1
        
        # Calculate yearly averages
        machine_info['yearly_totals']['average_oee'] = round(total_oee_sum / total_oee_count, 2) if total_oee_count > 0 else 0
        machine_info['yearly_totals']['average_reject_rate'] = round(total_reject_rate_sum / total_reject_rate_count, 2) if total_reject_rate_count > 0 else 0
        
        # Add targets (multiply monthly targets by 12 months)
        num_months = 12
        machine_info['yearly_totals']['target_booked_hours_header'] = 420.0 * num_months  # 105 * 4 weeks * 12 months
        machine_info['yearly_totals']['target_working_hours'] = 420.0 * num_months
        machine_info['yearly_totals']['target_output_qty'] = 340.0 * num_months  # 85 * 4 weeks * 12 months
        machine_info['yearly_totals']['target_oee'] = 85.0
        machine_info['yearly_totals']['target_reject_rate'] = 1.5
        
        # Calculate variances
        machine_info['yearly_totals']['variance_booked_hours_header'] = round(machine_info['yearly_totals']['total_booked_hours_header'] - machine_info['yearly_totals']['target_booked_hours_header'], 1)
        machine_info['yearly_totals']['variance_working_hours'] = round(machine_info['yearly_totals']['total_working_hours'] - machine_info['yearly_totals']['target_working_hours'], 1)
        machine_info['yearly_totals']['variance_output_qty'] = round(machine_info['yearly_totals']['total_output_qty'] - machine_info['yearly_totals']['target_output_qty'], 1)
        machine_info['yearly_totals']['variance_oee'] = round(machine_info['yearly_totals']['average_oee'] - machine_info['yearly_totals']['target_oee'], 1)
        machine_info['yearly_totals']['variance_reject_rate'] = round(machine_info['yearly_totals']['average_reject_rate'] - machine_info['yearly_totals']['target_reject_rate'], 1)
        
        # Calculate percentages
        machine_info['yearly_totals']['percent_booked_hours_header'] = round((machine_info['yearly_totals']['total_booked_hours_header'] / machine_info['yearly_totals']['target_booked_hours_header']) * 100, 1) if machine_info['yearly_totals']['target_booked_hours_header'] > 0 else 0
        machine_info['yearly_totals']['percent_working_hours'] = round((machine_info['yearly_totals']['total_working_hours'] / machine_info['yearly_totals']['target_working_hours']) * 100, 1) if machine_info['yearly_totals']['target_working_hours'] > 0 else 0
        machine_info['yearly_totals']['percent_output_qty'] = round((machine_info['yearly_totals']['total_output_qty'] / machine_info['yearly_totals']['target_output_qty']) * 100, 1) if machine_info['yearly_totals']['target_output_qty'] > 0 else 0
        machine_info['yearly_totals']['percent_oee'] = round((machine_info['yearly_totals']['average_oee'] / machine_info['yearly_totals']['target_oee']) * 100, 1) if machine_info['yearly_totals']['target_oee'] > 0 else 0
        
        machine_data.append(machine_info)
    
    # Calculate summary data for all machines
    summary_data = {
        'monthly_data': [],
        'yearly_totals': {
            'total_output_qty': 0,
            'total_booked_hours_header': 0,
            'total_working_hours': 0,
            'total_planned_production': 0,
            'total_rejects': 0,
            'total_cutbacks': 0,
            'total_wait_material': 0,
            'total_meetings': 0,
            'total_breakdown': 0,
            'total_change_over': 0,
            'total_operating_hours': 0,
            'total_non_recorded_time': 0,
            'average_oee': 0,
            'average_reject_rate': 0,
        }
    }
    
    # Aggregate monthly summaries across all machines
    for month in months:
        month_summary = {
            'month_number': month['month_number'],
            'month_name': month['month_name'],
            'month_full_name': month['month_full_name'],
            'start_date': month['start_date'],
            'end_date': month['end_date'],
            'booked_hours_header': 0,
            'working_hours': 0,
            'planned_production': 0,
            'output_qty': 0,
            'rejects': 0,
            'cutbacks': 0,
            'wait_material': 0,
            'meetings': 0,
            'breakdown': 0,
            'change_over': 0,
            'operating_hours': 0,
            'non_recorded_time': 0,
            'oee': 0,
            'reject_rate': 0,
        }
        
        oee_values = []
        reject_rates = []
        
        for machine_info in machine_data:
            for monthly_data in machine_info['monthly_data']:
                if monthly_data['month_number'] == month['month_number']:
                    month_summary['booked_hours_header'] += monthly_data['booked_hours_header']
                    month_summary['working_hours'] += monthly_data['working_hours']
                    month_summary['planned_production'] += monthly_data['planned_production']
                    month_summary['output_qty'] += monthly_data['output_qty']
                    month_summary['rejects'] += monthly_data['rejects']
                    month_summary['cutbacks'] += monthly_data['cutbacks']
                    month_summary['wait_material'] += monthly_data['wait_material']
                    month_summary['meetings'] += monthly_data['meetings']
                    month_summary['breakdown'] += monthly_data['breakdown']
                    month_summary['change_over'] += monthly_data['change_over']
                    month_summary['operating_hours'] += monthly_data['operating_hours']
                    month_summary['non_recorded_time'] += monthly_data['non_recorded_time']
                    
                    if monthly_data['oee'] > 0:
                        oee_values.append(monthly_data['oee'])
                    if monthly_data['reject_rate'] >= 0:
                        reject_rates.append(monthly_data['reject_rate'])
        
        month_summary['oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
        
        # FIXED: Calculate reject rate for summary with formula: ((Reject + Cutback) / (Output + Reject + Cutback)) × 100
        total_production = month_summary['output_qty'] + month_summary['rejects'] + month_summary['cutbacks']
        if total_production > 0:
            month_summary['reject_rate'] = round(((month_summary['rejects'] + month_summary['cutbacks']) / total_production * 100), 2)
        else:
            month_summary['reject_rate'] = 0
        
        summary_data['monthly_data'].append(month_summary)
    
    # Calculate yearly summary totals
    for month_summary in summary_data['monthly_data']:
        summary_data['yearly_totals']['total_booked_hours_header'] += month_summary['booked_hours_header']
        summary_data['yearly_totals']['total_working_hours'] += month_summary['working_hours']
        summary_data['yearly_totals']['total_planned_production'] += month_summary['planned_production']
        summary_data['yearly_totals']['total_output_qty'] += month_summary['output_qty']
        summary_data['yearly_totals']['total_rejects'] += month_summary['rejects']
        summary_data['yearly_totals']['total_cutbacks'] += month_summary['cutbacks']
        summary_data['yearly_totals']['total_wait_material'] += month_summary['wait_material']
        summary_data['yearly_totals']['total_meetings'] += month_summary['meetings']
        summary_data['yearly_totals']['total_breakdown'] += month_summary['breakdown']
        summary_data['yearly_totals']['total_change_over'] += month_summary['change_over']
        summary_data['yearly_totals']['total_operating_hours'] += month_summary['operating_hours']
        summary_data['yearly_totals']['total_non_recorded_time'] += month_summary['non_recorded_time']
    
    oee_values = [m['oee'] for m in summary_data['monthly_data'] if m['oee'] > 0]
    reject_values = [m['reject_rate'] for m in summary_data['monthly_data'] if m['reject_rate'] >= 0]
    
    summary_data['yearly_totals']['average_oee'] = round(sum(oee_values) / len(oee_values), 2) if oee_values else 0
    summary_data['yearly_totals']['average_reject_rate'] = round(sum(reject_values) / len(reject_values), 2) if reject_values else 0
    
    # Add summary targets
    num_machines = len(machines)
    num_months = 12
    summary_data['yearly_totals']['target_booked_hours_header'] = 420.0 * num_months * num_machines
    summary_data['yearly_totals']['target_working_hours'] = 420.0 * num_months * num_machines
    summary_data['yearly_totals']['target_output_qty'] = 340.0 * num_months * num_machines
    summary_data['yearly_totals']['target_oee'] = 85.0
    summary_data['yearly_totals']['target_reject_rate'] = 1.5
    
    # Calculate summary variances
    summary_data['yearly_totals']['variance_booked_hours_header'] = round(summary_data['yearly_totals']['total_booked_hours_header'] - summary_data['yearly_totals']['target_booked_hours_header'], 1)
    summary_data['yearly_totals']['variance_working_hours'] = round(summary_data['yearly_totals']['total_working_hours'] - summary_data['yearly_totals']['target_working_hours'], 1)
    summary_data['yearly_totals']['variance_output_qty'] = round(summary_data['yearly_totals']['total_output_qty'] - summary_data['yearly_totals']['target_output_qty'], 1)
    summary_data['yearly_totals']['variance_oee'] = round(summary_data['yearly_totals']['average_oee'] - summary_data['yearly_totals']['target_oee'], 1)
    summary_data['yearly_totals']['variance_reject_rate'] = round(summary_data['yearly_totals']['average_reject_rate'] - summary_data['yearly_totals']['target_reject_rate'], 1)
    
    # Calculate summary percentages
    summary_data['yearly_totals']['percent_booked_hours_header'] = round((summary_data['yearly_totals']['total_booked_hours_header'] / summary_data['yearly_totals']['target_booked_hours_header']) * 100, 1) if summary_data['yearly_totals']['target_booked_hours_header'] > 0 else 0
    summary_data['yearly_totals']['percent_working_hours'] = round((summary_data['yearly_totals']['total_working_hours'] / summary_data['yearly_totals']['target_working_hours']) * 100, 1) if summary_data['yearly_totals']['target_working_hours'] > 0 else 0
    summary_data['yearly_totals']['percent_output_qty'] = round((summary_data['yearly_totals']['total_output_qty'] / summary_data['yearly_totals']['target_output_qty']) * 100, 1) if summary_data['yearly_totals']['target_output_qty'] > 0 else 0
    summary_data['yearly_totals']['percent_oee'] = round((summary_data['yearly_totals']['average_oee'] / summary_data['yearly_totals']['target_oee']) * 100, 1) if summary_data['yearly_totals']['target_oee'] > 0 else 0
    
    context = {
        'year': year,
        'first_day': first_day,
        'last_day': last_day,
        'months': months,
        'machine_data': machine_data,
        'summary_data': summary_data,
        'active_menu': 'weld_report_oee_yearly'
    }
    
    return render(request, 'weld/report_oee_yearly.html', context)

@threading_access_required
def thread_excel_export(request):
    """Export Threading Records to Excel - GROUPED GLOBALLY BY BJO + OPERATION + DATE"""
    
    # Get filter parameters
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')
    filter_bjo = request.GET.get('bjo', '')

    # Filter headers sama seperti di thread_list
    headers = ThreadHeader.objects.select_related(
        'machine', 'shift', 'operator', 'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    if filter_bjo:
        headers = headers.filter(
            id__in=ThreadDetail.objects.filter(
                Q(bjo_number__icontains=filter_bjo) |
                Q(bjo__bjo__icontains=filter_bjo)
            ).values_list('Reff_id', flat=True)
        )

    headers = headers.order_by('-date', '-id')

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Threading Records"

    # Define styles
    header_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    header_font = Font(bold=True, size=11)
    center_alignment = Alignment(horizontal='center', vertical='center')
    
    # Define headers
    headers_list = [
        'Transaction Date',
        'Transaction Type',
        'Job',
        'Operation',
        'Next Operation',
        'Completed',
        'Total Hours',
        'Job Cost Rate',
        'Employee'
    ]
    
    # Write headers
    for col_num, header_text in enumerate(headers_list, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header_text
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_alignment

    # ✅ COLLECT ALL DETAILS FROM ALL FILTERED HEADERS
    all_details = ThreadDetail.objects.filter(
        Reff__in=headers
    ).select_related('bjo', 'Reff').order_by('Reff__date', 'bjo_number', 'job_operation')
    
    # Apply BJO filter to details if specified
    if filter_bjo:
        all_details = all_details.filter(
            Q(bjo_number__icontains=filter_bjo) |
            Q(bjo__bjo__icontains=filter_bjo)
        )
    
    # ✅ GROUP BY: Transaction_Date + BJO + Operation (GLOBAL GROUPING)
    grouped_data = defaultdict(lambda: {
        'transaction_date': None,
        'bjo_number': '',
        'job_operation': '',
        'total_output': 0,
        'total_hours': 0,
    })
    
    for detail in all_details:
        if not detail.bjo or not detail.Reff:
            continue
        
        # Create unique key: date + bjo + operation
        date_key = detail.Reff.date.strftime('%Y-%m-%d')
        bjo_key = detail.bjo_number if detail.bjo_number else (detail.bjo.bjo if detail.bjo else 'NONE')
        op_key = detail.job_operation or 'NONE'
        key = f"{date_key}_{bjo_key}_{op_key}"
        
        # Set basic info (first occurrence)
        if grouped_data[key]['transaction_date'] is None:
            grouped_data[key]['transaction_date'] = detail.Reff.date
        
        grouped_data[key]['bjo_number'] = bjo_key
        grouped_data[key]['job_operation'] = op_key
        
        # ✅ ACCUMULATE OUTPUT (0.5 + 0.5 = 1.0 untuk completion di header berbeda)
        if detail.output:
            grouped_data[key]['total_output'] += float(detail.output)
        
        # Accumulate hours
        if detail.start_time and detail.stop_time:
            duration = calculate_time_duration(detail.start_time, detail.stop_time)
            if duration:
                grouped_data[key]['total_hours'] += duration
    
    # Write data to Excel
    row_num = 2
    for key in sorted(grouped_data.keys()):
        data = grouped_data[key]
        
        # Transaction Date
        ws.cell(row=row_num, column=1).value = data['transaction_date'].strftime('%m/%d/%Y')
        ws.cell(row=row_num, column=1).alignment = center_alignment
        
        # Transaction Type
        ws.cell(row=row_num, column=2).value = "Run"
        ws.cell(row=row_num, column=2).alignment = center_alignment
        
        # Job (BJO with prefix BJO000)
        if data['bjo_number']:
            bjo_clean = data['bjo_number'].replace('BJO', '').strip()
            job_value = f"BJO000{bjo_clean}"
        else:
            job_value = ""
        ws.cell(row=row_num, column=3).value = job_value
        ws.cell(row=row_num, column=3).alignment = center_alignment
        
        # Operation
        ws.cell(row=row_num, column=4).value = data['job_operation']
        ws.cell(row=row_num, column=4).alignment = center_alignment
        
        # Next Operation (+10)
        try:
            next_op = int(data['job_operation']) + 10
            ws.cell(row=row_num, column=5).value = next_op
        except:
            ws.cell(row=row_num, column=5).value = ""
        ws.cell(row=row_num, column=5).alignment = center_alignment
        
        # ✅ COMPLETED - FIXED: Tampilkan dengan 1 desimal untuk handle 0.5
        ws.cell(row=row_num, column=6).value = round(data['total_output'], 1)
        ws.cell(row=row_num, column=6).alignment = center_alignment
        ws.cell(row=row_num, column=6).number_format = '0.0'  # Format: 0.5, 1.0, 1.5, 2.0
        
        # Total Hours
        ws.cell(row=row_num, column=7).value = round(data['total_hours'], 2)
        ws.cell(row=row_num, column=7).alignment = center_alignment
        ws.cell(row=row_num, column=7).number_format = '0.00'
        
        # Job Cost Rate
        ws.cell(row=row_num, column=8).value = 13.94
        ws.cell(row=row_num, column=8).alignment = center_alignment
        ws.cell(row=row_num, column=8).number_format = '0.00'
        
        # Employee
        ws.cell(row=row_num, column=9).value = "Thread"
        ws.cell(row=row_num, column=9).alignment = center_alignment
        
        row_num += 1

    # Adjust column widths
    column_widths = {
        'A': 18, 'B': 18, 'C': 15, 'D': 12, 
        'E': 18, 'F': 12, 'G': 13, 'H': 16, 'I': 12,
    }
    
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    
    # Generate filename with timestamp
    filename = f'Threading_Records_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Save workbook to response
    wb.save(response)
    
    return response

@welding_access_required
def weld_excel_export(request):
    """Export Welding Records to Excel dengan format sesuai requirement - GROUPED BY BJO"""
    
    # Get filter parameters
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')

    # Filter headers sama seperti di weld_list
    headers = WeldHeader.objects.select_related(
        'machine', 'shift', 'operator', 'booked_hours'
    ).all()

    if query:
        headers = headers.filter(
            Q(operator__name__icontains=query) |
            Q(operator__initial__icontains=query) |
            Q(comment__icontains=query) |
            Q(machine__name__icontains=query)
        )

    if filter_machine:
        headers = headers.filter(machine__name=filter_machine)

    if filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            headers = headers.filter(date=filter_date_obj)
        except ValueError:
            pass

    if filter_status:
        if filter_status == 'posted':
            headers = headers.filter(is_posted=True)
        elif filter_status == 'draft':
            headers = headers.filter(is_posted=False)

    headers = headers.order_by('-date', '-id')

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Welding Records"

    # Define styles
    header_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    header_font = Font(bold=True, size=11)
    center_alignment = Alignment(horizontal='center', vertical='center')
    
    # Define headers
    headers_list = [
        'Transaction Date',
        'Transaction Type',
        'Job',
        'Operation',
        'Next Operation',
        'Completed',
        'Total Hours',
        'Job Cost Rate',
        'Employee'
    ]
    
    # Write headers
    for col_num, header_text in enumerate(headers_list, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header_text
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_alignment

    # ✅ COLLECT ALL DETAILS FROM ALL FILTERED HEADERS
    all_details = WeldDetail.objects.filter(
        Reff__in=headers
    ).select_related('bjo', 'Reff').order_by('Reff__date', 'bjo', 'job_operation')
    
    # ✅ GROUP BY: Transaction_Date + BJO + Operation
    grouped_data = defaultdict(lambda: {
        'transaction_date': None,
        'bjo_number': '',
        'job_operation': '',
        'total_output': 0,
        'total_hours': 0,
    })
    
    for detail in all_details:
        if not detail.bjo or not detail.Reff:
            continue
        
        # Create unique key: date + bjo + operation
        date_key = detail.Reff.date.strftime('%Y-%m-%d')
        bjo_key = detail.bjo.bjo
        op_key = detail.job_operation or 'NONE'
        key = f"{date_key}_{bjo_key}_{op_key}"
        
        # Set basic info (first occurrence)
        if grouped_data[key]['transaction_date'] is None:
            grouped_data[key]['transaction_date'] = detail.Reff.date
        
        grouped_data[key]['bjo_number'] = bjo_key
        grouped_data[key]['job_operation'] = op_key
        
        # ✅ ACCUMULATE OUTPUT (0.5 + 0.5 = 1.0 untuk completion di header berbeda)
        if detail.output:
            grouped_data[key]['total_output'] += float(detail.output)
        
        # Accumulate hours
        if detail.start_time and detail.stop_time:
            duration = calculate_time_duration(detail.start_time, detail.stop_time)
            if duration:
                grouped_data[key]['total_hours'] += duration
    
    # Write data to Excel
    row_num = 2
    for key in sorted(grouped_data.keys()):
        data = grouped_data[key]
        
        # Transaction Date
        ws.cell(row=row_num, column=1).value = data['transaction_date'].strftime('%m/%d/%Y')
        ws.cell(row=row_num, column=1).alignment = center_alignment
        
        # Transaction Type
        ws.cell(row=row_num, column=2).value = "Run"
        ws.cell(row=row_num, column=2).alignment = center_alignment
        
        # Job (BJO with prefix BJO000)
        bjo_clean = data['bjo_number'].replace('BJO', '').strip()
        job_value = f"BJO000{bjo_clean}"
        ws.cell(row=row_num, column=3).value = job_value
        ws.cell(row=row_num, column=3).alignment = center_alignment
        
        # Operation
        ws.cell(row=row_num, column=4).value = data['job_operation']
        ws.cell(row=row_num, column=4).alignment = center_alignment
        
        # Next Operation (+10)
        try:
            next_op = int(data['job_operation']) + 10
            ws.cell(row=row_num, column=5).value = next_op
        except:
            ws.cell(row=row_num, column=5).value = ""
        ws.cell(row=row_num, column=5).alignment = center_alignment
        
        # ✅ COMPLETED - tampilkan dengan 2 desimal (bisa 0.5, 1.0, dll)
        ws.cell(row=row_num, column=6).value = round(data['total_output'], 2)
        ws.cell(row=row_num, column=6).alignment = center_alignment
        ws.cell(row=row_num, column=6).number_format = '0.00'
        
        # Total Hours
        ws.cell(row=row_num, column=7).value = round(data['total_hours'], 2)
        ws.cell(row=row_num, column=7).alignment = center_alignment
        ws.cell(row=row_num, column=7).number_format = '0.00'
        
        # Job Cost Rate
        ws.cell(row=row_num, column=8).value = 24.09
        ws.cell(row=row_num, column=8).alignment = center_alignment
        ws.cell(row=row_num, column=8).number_format = '0.00'
        
        # Employee
        ws.cell(row=row_num, column=9).value = "Weld"
        ws.cell(row=row_num, column=9).alignment = center_alignment
        
        row_num += 1

    # Adjust column widths
    column_widths = {
        'A': 18,  # Transaction Date
        'B': 18,  # Transaction Type
        'C': 15,  # Job
        'D': 12,  # Operation
        'E': 18,  # Next Operation
        'F': 12,  # Completed
        'G': 13,  # Total Hours
        'H': 16,  # Job Cost Rate
        'I': 12,  # Employee
    }
    
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    
    # Generate filename with timestamp
    filename = f'Welding_Records_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Save workbook to response
    wb.save(response)
    
    return response


@connector_access_required
def connector_list(request):
    """View untuk menampilkan daftar connector dengan filter"""
    query = request.GET.get('q', '')
    filter_bjo = request.GET.get('bjo', '')
    filter_joint = request.GET.get('joint', '')

    connectors = Connector.objects.select_related('bjo').all()

    # Filter pencarian
    if query:
        connectors = connectors.filter(
            Q(joint_number__icontains=query) |
            Q(conn_number__icontains=query) |
            Q(bjo__bjo__icontains=query)
        )

    # Filter BJO
    if filter_bjo:
        connectors = connectors.filter(bjo__bjo=filter_bjo)

    # Filter Joint Number
    if filter_joint:
        connectors = connectors.filter(joint_number__icontains=filter_joint)

    connectors = connectors.order_by('-id')

    # Pagination
    paginator = Paginator(connectors, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opsi BJO untuk dropdown (unique bjo dari Connector yang sudah ada)
    bjo_options = Connector.objects.values_list('bjo__bjo', flat=True).distinct().order_by('bjo__bjo')

    context = {
        'connectors': page_obj,
        'query': query,
        'filter_bjo': filter_bjo,
        'filter_joint': filter_joint,
        'bjo_options': bjo_options,
        'active_menu': 'connector_list',
    }

    return render(request, 'connector/list.html', context)


# ✅ FIXED: Fungsi ini harus di luar decorator untuk endpoint AJAX
def get_joint_numbers_for_connector(request):
    """
    AJAX endpoint untuk mengambil joint numbers berdasarkan BJO yang dipilih.
    ✅ MENAMPILKAN SEMUA JOINT (karena 1 joint bisa punya banyak connector)
    
    ✅ TIDAK PAKAI DECORATOR - harus bisa diakses tanpa redirect
    """
    # Debug log
    print(f"=== AJAX Request Debug ===")
    print(f"Method: {request.method}")
    print(f"Path: {request.path}")
    print(f"GET params: {request.GET}")
    
    # Hanya izinkan GET request
    if request.method != 'GET':
        return JsonResponse({
            'success': False,
            'error': 'Method not allowed. Use GET request.',
            'joint_numbers': []
        }, status=405)
    
    bjo_id = request.GET.get('bjo_id')
    
    # Validasi bjo_id
    if not bjo_id:
        return JsonResponse({
            'success': False,
            'error': 'BJO ID is required',
            'joint_numbers': []
        }, status=400)
    
    try:
        # Get BJO
        bjo = JobHeader.objects.get(id=bjo_id)
        
        # ✅ AMBIL SEMUA joint numbers dari SerialNumber untuk BJO ini
        all_joints = SerialNumber.objects.filter(
            bjo=bjo
        ).values_list('joint_number', flat=True).distinct().order_by('joint_number')
        
        # Convert to list
        all_joints_list = list(all_joints)
        
        # ✅ HITUNG berapa connector yang sudah ada untuk setiap joint
        # Ini untuk INFO saja, BUKAN untuk filtering
        existing_connectors = Connector.objects.filter(
            bjo=bjo
        ).values('joint_number').annotate(
            conn_count=Count('id')
        )
        
        # Buat mapping: joint_number -> jumlah connector
        joint_connector_map = {
            item['joint_number']: item['conn_count'] 
            for item in existing_connectors
        }
        
        # ✅ TAMBAHKAN info jumlah connector ke setiap joint
        joint_info_list = []
        for joint in all_joints_list:
            conn_count = joint_connector_map.get(joint, 0)
            joint_info_list.append({
                'joint_number': joint,
                'connector_count': conn_count
            })
        
        # Prepare response
        response_data = {
            'success': True,
            'joint_numbers': all_joints_list,  # ✅ SEMUA joint, tidak di-filter
            'joint_info': joint_info_list,      # ✅ Info tambahan per joint
            'total_joints': len(all_joints_list),
            'total_connectors': sum(joint_connector_map.values()),
            'bjo_info': {
                'bjo': bjo.bjo,
                'customer': bjo.customer or '-',
                'size': str(bjo.size) if bjo.size else '-',
                'conn': str(bjo.conn) if bjo.conn else '-',
                'process': str(bjo.process_type) if bjo.process_type else '-',
                'product': bjo.product or '-'
            }
        }
        
        print(f"✅ Response: {len(all_joints_list)} joints, {sum(joint_connector_map.values())} total connectors")
        
        return JsonResponse(response_data)
    
    except JobHeader.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'BJO not found',
            'joint_numbers': []
        }, status=404)
    
    except Exception as e:
        # Log error untuk debugging
        import traceback
        print(f"❌ Error in get_joint_numbers_for_connector: {str(e)}")
        print(traceback.format_exc())
        
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}',
            'joint_numbers': []
        }, status=500)


@connector_write_access_required
def connector_add(request):
    """View untuk menambah connector baru dengan filtering BJO"""
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        joint_number = request.POST.get('joint_number', '').strip()
        conn_number_raw = request.POST.get('conn_number', '')

        # ✅ CLEAN: Hapus semua spasi dari conn_number
        conn_number = clean_conn_number(conn_number_raw)

        # Validasi wajib isi
        if not bjo_id or not joint_number or not conn_number:
            messages.error(request, "BJO, Joint Number, dan Connector Number wajib diisi.")
            return redirect('connector_add')

        try:
            bjo = JobHeader.objects.get(id=bjo_id)
        except JobHeader.DoesNotExist:
            messages.error(request, "BJO tidak ditemukan.")
            return redirect('connector_add')

        # Validasi: Cek apakah BJO ini valid untuk connector
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        if 'THREAD' in process_name:
            # Threading: harus punya connection XLW-S, XLW-GT, atau XLW
            conn_name = bjo.conn.name.upper() if bjo.conn else ''
            valid_connections = ['XLW-S', 'XLW-GT', 'XLW']
            
            if not any(vc in conn_name for vc in valid_connections):
                messages.error(
                    request,
                    f"BJO Threading harus memiliki connection XLW-S, XLW-GT, atau XLW. "
                    f"BJO ini memiliki connection: {bjo.conn.name if bjo.conn else 'None'}"
                )
                return redirect('connector_add')

        # Validasi: Cek apakah joint number valid untuk BJO ini
        joint_exists = SerialNumber.objects.filter(
            bjo=bjo,
            joint_number=joint_number
        ).exists()
        
        if not joint_exists:
            messages.error(
                request,
                f"Joint Number '{joint_number}' tidak ditemukan pada BJO '{bjo.bjo}'. "
                f"Silakan pilih joint number yang valid."
            )
            return redirect('connector_add')

        # ✅ VALIDASI: conn_number harus GLOBALLY UNIQUE (tidak peduli BJO atau Joint)
        existing_conn = Connector.objects.filter(conn_number=conn_number).first()

        if existing_conn:
            messages.error(
                request,
                f"Connector Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
            )
            return redirect('connector_add')

        # ✅ CEK DUPLIKAT: Cek apakah kombinasi BJO + Joint + Conn sudah ada
        duplicate_check = Connector.objects.filter(
            bjo=bjo,
            joint_number=joint_number,
            conn_number=conn_number
        ).first()

        if duplicate_check:
            messages.warning(
                request,
                f"Data connector ini sudah ada: BJO {bjo.bjo}, Joint {joint_number} → Conn {conn_number}"
            )
            return redirect('connector_list')

        # Create connector
        try:
            connector = Connector.objects.create(
                bjo=bjo,
                joint_number=joint_number,
                conn_number=conn_number
            )
            messages.success(
                request,
                f"Connector berhasil ditambahkan: BJO {bjo.bjo}, Joint {joint_number} → Conn {conn_number}"
            )
            return redirect('connector_list')
        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('connector_add')

    # GET method - tampilkan form
    job_list_weld = JobHeader.objects.filter(
        is_finish=False,
        process_type__name__icontains='WELD'
    ).order_by('bjo')
    
    job_list_thread = JobHeader.objects.filter(
        is_finish=False,
        process_type__name__icontains='THREAD',
        conn__name__iregex=r'(XLW-S|XLW-GT|XLW)'
    ).order_by('bjo')
    
    job_list = list(job_list_weld) + list(job_list_thread)
    job_list.sort(key=lambda x: x.bjo)

    context = {
        'job_list': job_list,
        'active_menu': 'connector_list',
    }

    return render(request, 'connector/add.html', context)


@connector_write_access_required
def connector_edit(request, connector_id):
    """View untuk edit connector - hanya connector number yang bisa diubah"""
    connector = get_object_or_404(Connector, pk=connector_id)

    if request.method == 'POST':
        conn_number_raw = request.POST.get('conn_number', '')
        conn_number = clean_conn_number(conn_number_raw)

        if not conn_number:
            messages.error(request, "Connector Number wajib diisi.")
            return redirect('connector_edit', connector_id=connector.id)

        # ✅ VALIDASI: conn_number harus GLOBALLY UNIQUE
        # Exclude current record (by ID, bukan by BJO+Joint)
        existing_conn = Connector.objects.filter(
            conn_number=conn_number
        ).exclude(id=connector.id).first()

        if existing_conn:
            messages.error(
                request,
                f"Connector Number '{conn_number}' sudah digunakan oleh BJO '{existing_conn.bjo.bjo}' "
                f"Joint '{existing_conn.joint_number}'. Silakan gunakan nomor lain."
            )
            return redirect('connector_edit', connector_id=connector.id)

        try:
            connector.conn_number = conn_number
            connector.save()

            messages.success(
                request,
                f"Connector berhasil diupdate: Joint {connector.joint_number} → Conn {conn_number}"
            )
            return redirect('connector_list')
        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('connector_edit', connector_id=connector.id)

    context = {
        'connector': connector,
        'active_menu': 'connector_list',
    }

    return render(request, 'connector/edit.html', context)

@connector_delete_access_required
def connector_delete(request, connector_id):
    """View untuk delete connector"""
    connector = get_object_or_404(Connector, pk=connector_id)

    if request.method != 'POST':
        messages.error(request, "Method tidak diizinkan.")
        return redirect('connector_list')

    try:
        joint_number = connector.joint_number
        conn_number = connector.conn_number
        bjo_name = connector.bjo.bjo

        connector.delete()

        messages.success(
            request,
            f"Connector berhasil dihapus: BJO {bjo_name}, Joint {joint_number}, Conn {conn_number}"
        )
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus: {str(e)}")

    return redirect('connector_list')

def tracking_hours(request):
    """
    View untuk tracking total hours semua BJO dengan filter
    OPTIMIZED: Data tidak di-load secara default untuk performa yang lebih baik
    User HARUS apply filter terlebih dahulu sebelum data ditampilkan
    """
    # Get filter parameters
    selected_bjo = request.GET.get('bjo', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    selected_process = request.GET.get('process', '')
    selected_machine = request.GET.get('machine', '')
    selected_operator = request.GET.get('operator', '')
    selected_shift = request.GET.get('shift', '')
    selected_status = request.GET.get('status', '')
    selected_output = request.GET.get('output_filter', '')
    joint_number = request.GET.get('joint_number', '')
    
    # Initialize empty data
    tracking_data = []
    total_hours = 0
    total_joints = 0
    avg_hours_per_joint = 0
    total_bjos = 0
    group_by_bjo_list = []
    
    # Check if any filter is applied
    has_filter = any([
        selected_bjo, date_from, date_to, selected_process, 
        selected_machine, selected_operator, selected_shift, 
        selected_status, selected_output, joint_number
    ])
    
    # Only load data if filter is applied
    if has_filter:
        # Initialize queries
        thread_details = ThreadDetail.objects.select_related(
            'Reff__machine', 'Reff__operator', 'Reff__shift', 'bjo'
        ).all()
        
        weld_details = WeldDetail.objects.select_related(
            'Reff__machine', 'Reff__operator', 'Reff__shift', 'bjo'
        ).all()
        
        # Apply filters
        if selected_bjo:
            thread_details = thread_details.filter(bjo_id=selected_bjo)
            weld_details = weld_details.filter(bjo_id=selected_bjo)
        
        if date_from:
            thread_details = thread_details.filter(Reff__date__gte=date_from)
            weld_details = weld_details.filter(Reff__date__gte=date_from)
        
        if date_to:
            thread_details = thread_details.filter(Reff__date__lte=date_to)
            weld_details = weld_details.filter(Reff__date__lte=date_to)
        
        if selected_machine:
            thread_details = thread_details.filter(Reff__machine_id=selected_machine)
            weld_details = weld_details.filter(Reff__machine_id=selected_machine)
        
        if selected_operator:
            thread_details = thread_details.filter(Reff__operator_id=selected_operator)
            weld_details = weld_details.filter(Reff__operator_id=selected_operator)
        
        if selected_shift:
            thread_details = thread_details.filter(Reff__shift_id=selected_shift)
            weld_details = weld_details.filter(Reff__shift_id=selected_shift)
        
        if joint_number:
            thread_details = thread_details.filter(joint_number__icontains=joint_number)
            weld_details = weld_details.filter(joint_number__icontains=joint_number)
        
        # Apply process filter
        if not selected_process or selected_process == 'THREAD':
            for detail in thread_details:
                if not detail.Reff:
                    continue
                
                # Determine status
                has_ncr = ThreadNcr.objects.filter(serial=detail).exists()
                comment = detail.comment or ''
                
                if 'REWORKED' in comment.upper():
                    status = 'REWORK'
                elif 'UNCOMPLETED' in comment.upper() or detail.is_uncompleted:
                    status = 'UNCOMPLETED'
                elif has_ncr:
                    status = 'NCR'
                else:
                    status = 'COMPLETED'
                
                # MENGGUNAKAN fungsi calculate_time_duration yang sudah ada
                duration = calculate_time_duration(detail.start_time, detail.stop_time)
                if duration is None:
                    duration = 0
                
                tracking_data.append({
                    'date': detail.Reff.date,
                    'bjo_id': detail.bjo.id if detail.bjo else None,
                    'bjo_number': detail.bjo.bjo if detail.bjo else '-',
                    'customer': detail.bjo.customer if detail.bjo else '-',
                    'joint_number': detail.joint_number or '-',
                    'process': 'THREAD',
                    'side': detail.pin_or_box or '-',
                    'machine': detail.Reff.machine.name if detail.Reff.machine else '-',
                    'operator': detail.Reff.operator.name if detail.Reff.operator else '-',
                    'shift': detail.Reff.shift.name if detail.Reff.shift else '-',
                    'start_time': detail.start_time,
                    'stop_time': detail.stop_time,
                    'duration': duration,
                    'output': detail.output or 0,
                    'status': status,
                    'comment': detail.comment or '-',
                })
        
        if not selected_process or selected_process == 'WELD':
            for detail in weld_details:
                if not detail.Reff:
                    continue
                
                # Determine status
                has_ncr = WeldNcr.objects.filter(serial=detail).exists()
                comment = detail.comment or ''
                
                if 'REWORKED' in comment.upper():
                    status = 'REWORK'
                elif 'UNCOMPLETED' in comment.upper() or detail.is_uncompleted:
                    status = 'UNCOMPLETED'
                elif has_ncr:
                    status = 'NCR'
                else:
                    status = 'COMPLETED'
                
                # MENGGUNAKAN fungsi calculate_time_duration yang sudah ada
                duration = calculate_time_duration(detail.start_time, detail.stop_time)
                if duration is None:
                    duration = 0
                
                tracking_data.append({
                    'date': detail.Reff.date,
                    'bjo_id': detail.bjo.id if detail.bjo else None,
                    'bjo_number': detail.bjo.bjo if detail.bjo else '-',
                    'customer': detail.bjo.customer if detail.bjo else '-',
                    'joint_number': detail.joint_number or '-',
                    'process': 'WELD',
                    'side': detail.pin_or_box or '-',
                    'machine': detail.Reff.machine.name if detail.Reff.machine else '-',
                    'operator': detail.Reff.operator.name if detail.Reff.operator else '-',
                    'shift': detail.Reff.shift.name if detail.Reff.shift else '-',
                    'start_time': detail.start_time,
                    'stop_time': detail.stop_time,
                    'duration': duration,
                    'output': detail.output or 0,
                    'status': status,
                    'comment': detail.comment or '-',
                })
        
        # Sort by date descending
        tracking_data.sort(key=lambda x: (x['date'] or datetime.min.date(), x['start_time'] or datetime.min.time()), reverse=True)
        
        # Apply status filter (setelah semua data dikumpulkan)
        if selected_status:
            tracking_data = [item for item in tracking_data if item['status'] == selected_status]
        
        # Apply output filter
        if selected_output:
            if selected_output == 'gte_1':
                # Output >= 1.00
                tracking_data = [item for item in tracking_data if item['output'] >= 1]
            elif selected_output == 'lt_1':
                # Output < 1.00
                tracking_data = [item for item in tracking_data if item['output'] < 1]
        
        # Calculate summary statistics
        total_hours = sum(item['duration'] for item in tracking_data)
        total_joints = len(set(item['joint_number'] for item in tracking_data if item['joint_number'] != '-'))
        avg_hours_per_joint = total_hours / total_joints if total_joints > 0 else 0
        total_bjos = len(set(item['bjo_number'] for item in tracking_data if item['bjo_number'] != '-'))
        
        # Group by BJO for summary
        group_by_bjo = {}
        for item in tracking_data:
            bjo_num = item['bjo_number']
            if bjo_num == '-':
                continue
            
            if bjo_num not in group_by_bjo:
                group_by_bjo[bjo_num] = {
                    'bjo_id': item['bjo_id'],
                    'bjo_number': bjo_num,
                    'customer': item['customer'],
                    'process_type': item['process'],
                    'total_hours': 0,
                    'total_joints': set(),
                }
            
            group_by_bjo[bjo_num]['total_hours'] += item['duration']
            group_by_bjo[bjo_num]['total_joints'].add(item['joint_number'])
        
        # Convert set to count and calculate average
        for bjo_num, data in group_by_bjo.items():
            joint_count = len(data['total_joints'])
            group_by_bjo_list.append({
                'bjo_id': data['bjo_id'],
                'bjo_number': data['bjo_number'],
                'customer': data['customer'],
                'process_type': data['process_type'],
                'total_hours': data['total_hours'],
                'total_joints': joint_count,
                'avg_hours': data['total_hours'] / joint_count if joint_count > 0 else 0,
            })
        
        # Sort by total hours descending
        group_by_bjo_list.sort(key=lambda x: x['total_hours'], reverse=True)
    
    # Get all filter options (always loaded for dropdown)
    all_bjo = JobHeader.objects.all().order_by('-bjo')
    all_machines = Machine.objects.all().order_by('name')
    all_operators = Operator.objects.all().order_by('name')
    all_shifts = Shift.objects.all().order_by('name')
    
    context = {
        'tracking_data': tracking_data,
        'total_hours': total_hours,
        'total_joints': total_joints,
        'avg_hours_per_joint': avg_hours_per_joint,
        'total_bjos': total_bjos,
        'group_by_bjo': group_by_bjo_list,
        'has_filter': has_filter,
        
        # Filter options
        'all_bjo': all_bjo,
        'all_machines': all_machines,
        'all_operators': all_operators,
        'all_shifts': all_shifts,
        
        # Selected filters
        'selected_bjo': selected_bjo,
        'date_from': date_from,
        'date_to': date_to,
        'selected_process': selected_process,
        'selected_machine': selected_machine,
        'selected_operator': selected_operator,
        'selected_shift': selected_shift,
        'selected_status': selected_status,
        'selected_output': selected_output,
        'joint_number': joint_number,
        
        'active_menu': 'tracking_hours',
    }
    
    return render(request, 'joborder/tracking_hours.html', context)

@admin_required
def fix_data(request):
    """Tool untuk memperbaiki data weld multi-stage yang lama"""
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'fix_all':
            try:
                with transaction.atomic():
                    fixed_count = 0
                    error_count = 0
                    
                    # Find all unique combinations (bjo, joint_number, pin_or_box)
                    combinations = WeldDetail.objects.values(
                        'bjo', 'joint_number', 'pin_or_box'
                    ).annotate(
                        total=Count('id')
                    ).filter(total__gt=1)  # Only multi-stage (2+ records)
                    
                    for combo in combinations:
                        try:
                            bjo = JobHeader.objects.get(id=combo['bjo'])
                            joint_number = combo['joint_number']
                            pin_or_box = combo['pin_or_box']
                            
                            # Get all details for this combination
                            combo_details = WeldDetail.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number,
                                pin_or_box=pin_or_box
                            ).order_by('created_at')
                            
                            total_stages = combo_details.count()
                            
                            # Check if there's any COMPLETED stage
                            has_completed = combo_details.filter(is_uncompleted=False).exists()
                            
                            if has_completed:
                                needs_fix = False
                                
                                # ===== FIX STATUS =====
                                uncompleted_count = combo_details.filter(is_uncompleted=True).count()
                                
                                if uncompleted_count > 0:
                                    needs_fix = True
                                    # Fix: semua harus COMPLETED
                                    for detail in combo_details:
                                        if detail.is_uncompleted:
                                            old_comment = detail.comment or ''
                                            
                                            if 'UNCOMPLETED' in old_comment:
                                                new_comment = old_comment.replace('UNCOMPLETED', 'COMPLETED')
                                            else:
                                                new_comment = f"COMPLETED | {old_comment}" if old_comment else "COMPLETED"
                                            
                                            detail.comment = new_comment
                                            detail.is_uncompleted = False
                                            detail.save(update_fields=['comment', 'is_uncompleted'])
                                
                                # ===== FIX OUTPUT =====
                                # Calculate correct output per stage
                                correct_output = Decimal('1.0') / total_stages
                                correct_output = correct_output.quantize(Decimal('0.001'))
                                
                                # Check if any output is wrong
                                total_assigned = Decimal('0')
                                for i, detail in enumerate(combo_details):
                                    if i == total_stages - 1:
                                        # Last stage
                                        expected_output = Decimal('1.0') - (correct_output * (total_stages - 1))
                                    else:
                                        expected_output = correct_output
                                    
                                    if detail.output != expected_output:
                                        needs_fix = True
                                
                                # Recalculate all outputs
                                if needs_fix:
                                    total_assigned = Decimal('0')
                                    for i, detail in enumerate(combo_details):
                                        if i == total_stages - 1:
                                            detail.output = Decimal('1.0') - total_assigned
                                        else:
                                            detail.output = correct_output
                                            total_assigned += correct_output
                                        
                                        detail.save(update_fields=['output'])
                                    
                                    fixed_count += 1
                        
                        except Exception as e:
                            error_count += 1
                            print(f"Error fixing combo {combo}: {str(e)}")
                            continue
                    
                    if error_count > 0:
                        messages.warning(
                            request,
                            f"Fixed {fixed_count} combinations, but {error_count} errors occurred. Check console for details."
                        )
                    else:
                        messages.success(
                            request,
                            f"✅ Successfully fixed {fixed_count} multi-stage weld combinations!"
                        )
                    
                    return redirect('fix_data')
                    
            except Exception as e:
                messages.error(request, f"Error during fix process: {str(e)}")
                return redirect('fix_data')
        
        elif action == 'fix_single':
            detail_ids = request.POST.getlist('detail_ids[]')
            
            if not detail_ids:
                messages.error(request, "No details selected")
                return redirect('fix_data')
            
            try:
                with transaction.atomic():
                    # Get first detail to identify the combination
                    first_detail = WeldDetail.objects.get(id=detail_ids[0])
                    
                    # Get all details for this combination
                    combo_details = WeldDetail.objects.filter(
                        bjo=first_detail.bjo,
                        joint_number=first_detail.joint_number,
                        pin_or_box=first_detail.pin_or_box
                    ).order_by('created_at')
                    
                    total_stages = combo_details.count()
                    
                    # Fix status - all should be COMPLETED
                    for detail in combo_details:
                        if detail.is_uncompleted:
                            old_comment = detail.comment or ''
                            new_comment = old_comment.replace('UNCOMPLETED', 'COMPLETED')
                            detail.comment = new_comment
                            detail.is_uncompleted = False
                            detail.save(update_fields=['comment', 'is_uncompleted'])
                    
                    # Recalculate outputs
                    correct_output = Decimal('1.0') / total_stages
                    correct_output = correct_output.quantize(Decimal('0.001'))
                    
                    total_assigned = Decimal('0')
                    for i, detail in enumerate(combo_details):
                        if i == total_stages - 1:
                            detail.output = Decimal('1.0') - total_assigned
                        else:
                            detail.output = correct_output
                            total_assigned += correct_output
                        
                        detail.save(update_fields=['output'])
                    
                    messages.success(
                        request,
                        f"✅ Fixed BJO {first_detail.bjo.bjo} - Joint {first_detail.joint_number} - {first_detail.pin_or_box}"
                    )
                    
                    return redirect('fix_data')
                    
            except Exception as e:
                messages.error(request, f"Error fixing combination: {str(e)}")
                return redirect('fix_data')
    
    # ===== GET REQUEST - Show preview of issues =====
    issues = []
    
    # Find all multi-stage combinations
    combinations = WeldDetail.objects.values(
        'bjo', 'joint_number', 'pin_or_box'
    ).annotate(
        total=Count('id')
    ).filter(total__gt=1)
    
    for combo in combinations:
        try:
            bjo = JobHeader.objects.get(id=combo['bjo'])
            joint_number = combo['joint_number']
            pin_or_box = combo['pin_or_box']
            
            combo_details = WeldDetail.objects.filter(
                bjo=bjo,
                joint_number=joint_number,
                pin_or_box=pin_or_box
            ).order_by('created_at')
            
            total_stages = combo_details.count()
            
            # Check for issues
            has_completed = combo_details.filter(is_uncompleted=False).exists()
            uncompleted_count = combo_details.filter(is_uncompleted=True).count()
            
            # Check output correctness
            correct_output = Decimal('1.0') / total_stages
            correct_output = correct_output.quantize(Decimal('0.001'))
            
            has_wrong_output = False
            output_issues = []
            
            for i, detail in enumerate(combo_details):
                if i == total_stages - 1:
                    expected = Decimal('1.0') - (correct_output * (total_stages - 1))
                else:
                    expected = correct_output
                
                if detail.output != expected:
                    has_wrong_output = True
                    output_issues.append({
                        'stage': i + 1,
                        'current': detail.output,
                        'expected': expected
                    })
            
            # Only add to issues if there's a problem
            if (has_completed and uncompleted_count > 0) or has_wrong_output:
                
                # Prepare detail list with status
                detail_list = []
                for i, detail in enumerate(combo_details):
                    if i == total_stages - 1:
                        expected_output = Decimal('1.0') - (correct_output * (total_stages - 1))
                    else:
                        expected_output = correct_output
                    
                    detail_list.append({
                        'id': detail.id,
                        'stage': i + 1,
                        'status': 'UNCOMPLETED' if detail.is_uncompleted else 'COMPLETED',
                        'output': detail.output,
                        'expected_output': expected_output,
                        'comment': detail.comment or '-',
                        'created_at': detail.created_at,
                        'is_wrong_status': detail.is_uncompleted and has_completed,
                        'is_wrong_output': detail.output != expected_output
                    })
                
                issues.append({
                    'bjo': bjo.bjo,
                    'bjo_id': bjo.id,
                    'joint_number': joint_number,
                    'pin_or_box': pin_or_box,
                    'total_stages': total_stages,
                    'uncompleted_stages': uncompleted_count,
                    'has_status_issue': has_completed and uncompleted_count > 0,
                    'has_output_issue': has_wrong_output,
                    'output_issues': output_issues,
                    'details': detail_list,
                    'correct_output_per_stage': correct_output
                })
                
        except Exception as e:
            print(f"Error processing combo {combo}: {str(e)}")
            continue
    
    context = {
        'issues': issues,
        'total_issues': len(issues)
    }
    
    return render(request, 'fix/fix_data.html', context)