from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Case, When, F
from datetime import datetime, date
from .models import *
from production.models import *
from .decorators import *
from django.http import JsonResponse
from django.db import transaction

@beveling_access_required
def bevel_list(request):
    """List semua BevelHeader dengan filter dan pagination"""
    query = request.GET.get('q', '')
    filter_machine = request.GET.get('machine', '')
    filter_date = request.GET.get('date', '')
    filter_status = request.GET.get('status', '')
    filter_bjo = request.GET.get('bjo', '')

    headers = BevelHeader.objects.select_related(
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
            id__in=BevelDetail.objects.filter(
                Q(bjo_number__icontains=filter_bjo) |
                Q(bjo__bjo__icontains=filter_bjo)
            ).values_list('Reff_id', flat=True)
        )

    headers = headers.order_by('-date', '-id')
    
    # Hitung actual_hours dan total output
    for header in headers:
        if not header.is_posted:
            detail_qs = BevelDetail.objects.filter(Reff=header)
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

    # Get distinct BJO numbers for filter dropdown
    bjo_options = BevelDetail.objects.filter(
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
        'active_menu': 'bevel_list',
    }

    return render(request, 'bevel/list.html', context)


@beveling_write_access_required
def bevel_delete(request, header_id):
    header = get_object_or_404(BevelHeader, id=header_id)
    
    if request.method == 'POST':
        try:
            # Cek apakah sudah posted
            if header.is_posted:
                messages.error(request, 'Data tidak dapat dihapus karena sudah di-posting.')
                return redirect('bevel_list')
            bevel_info = f"{header.machine.name} - {header.date.strftime('%d/%m/%Y')}"
            header.delete()
            
            messages.success(request, f'Record beveling {bevel_info} berhasil dihapus.')
            return redirect('bevel_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('bevel_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('bevel_list')


@beveling_write_access_required
def bevel_header(request):
    """Create new BevelHeader record with minimal fields"""
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
                    return render(request, 'bevel/header.html', get_context_data(request.user))

                # Ambil foreign keys
                try:
                    machine = Machine.objects.get(id=request.POST.get('machine'))
                    shift = Shift.objects.get(id=request.POST.get('shift'))
                    operator = Operator.objects.get(id=request.POST.get('operator'))
                    booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
                except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                    messages.error(request, "Data yang dipilih tidak valid.")
                    return render(request, 'bevel/header.html', get_context_data(request.user))

                # Buat record baru
                header = BevelHeader.objects.create(
                    date=date_obj,
                    machine=machine,
                    shift=shift,
                    operator=operator,
                    booked_hours=booked_hours
                )

                messages.success(request, "Beveling Record berhasil disimpan.")
                return redirect('bevel_detail', header_id=header.pk)

            except Exception as e:
                messages.error(request, f"Terjadi kesalahan: {str(e)}")

    return render(request, 'bevel/header.html', get_context_data(request.user))


def get_context_data(user, for_edit=False):
    """Data untuk form Bevel Header"""
    # Filter mesin untuk BEVEL/THREADING process
    bevel_machines = Machine.objects.filter(
        process_type__name__icontains='threading'
    ).order_by('name')

    # Filter operator berdasarkan position = 'THREAD'
    bevel_operators = Operator.objects.filter(
        position='THREAD'
    ).order_by('name')
    
    # Fallback jika tidak ada operator dengan position THREAD
    if not bevel_operators.exists():
        bevel_operators = Operator.objects.all().order_by('name')
    
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
        'machine_list': bevel_machines,
        'shift_list': Shift.objects.all().order_by('name'),
        'operator_list': bevel_operators,
        'booked_hours_list': booked_hours_list,
    }


@beveling_write_access_required
def bevel_edit(request, header_id):
    """Edit BevelHeader - dengan auto revert posted status ketika ada perubahan"""
    header = get_object_or_404(BevelHeader, pk=header_id)
    
    # ===== CEK AKSES DAN AUTO REVERT UNTUK POSTED RECORDS =====
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit posted records.'
            )
            return redirect('bevel_list')

    if request.method == 'POST':
        try:
            # Validasi tanggal
            try:
                date_obj = datetime.strptime(request.POST.get('date'), "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Format tanggal tidak valid.")
                return render(request, 'bevel/edit.html', {**get_context_data(request.user, for_edit=True), 'header': header})

            # Ambil foreign keys
            try:
                machine = Machine.objects.get(id=request.POST.get('machine'))
                shift = Shift.objects.get(id=request.POST.get('shift'))
                operator = Operator.objects.get(id=request.POST.get('operator'))
                booked_hours = BookedHours.objects.get(id=request.POST.get('booked_hours'))
            except (Machine.DoesNotExist, Shift.DoesNotExist, Operator.DoesNotExist, BookedHours.DoesNotExist):
                messages.error(request, "Data yang dipilih tidak valid.")
                return render(request, 'bevel/edit.html', {**get_context_data(request.user, for_edit=True), 'header': header})

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
                messages.success(request, "Beveling Record berhasil diperbarui.")
            else:
                messages.info(request, "Tidak ada perubahan data.")
            
            return redirect('bevel_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")

    context = get_context_data(request.user, for_edit=True)
    context['header'] = header
    return render(request, 'bevel/edit.html', context)


def calculate_time_duration(start_time, stop_time):
    """
    Fungsi untuk menghitung durasi waktu dengan mempertimbangkan:
    1. Cross-midnight shift
    2. Lunch break (dikurangi 1 jam jika melewati jam 12:00 PM atau 12:00 AM)
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


def calculate_bevel_output(bjo, is_uncompleted):
    """
    Calculate output value for beveling based on completion status and BJO type
    OUTPUT UNTUK LAPORAN PRODUKSI BEVEL:
    - Box/Pin: 1 (completed) atau 0.5 (uncompleted)
    - Pipe: 1 (completed) atau 0.5 (uncompleted)
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
            elif 'PIPE' in bjo_for or 'BEVEL' in bjo_for:
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


def get_bevel_connector_info(request):
    """Check if BJO requires connector number for beveling"""
    bjo_id = request.GET.get('bjo_id')
    
    if not bjo_id:
        return JsonResponse({'requires_connector': False})
    
    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        # BEVEL menggunakan logika threading connector
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


def get_bevel_connector_number(request):
    """Get existing connector number for a joint in beveling"""
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


@beveling_access_required
def bevel_detail(request, header_id):
    header = get_object_or_404(BevelHeader, pk=header_id)

    if request.method == 'POST':
        # ===== CEK AKSES UNTUK POSTED RECORDS =====
        if header.is_posted:
            if request.user.role not in ['admin', 'supervisor']:
                messages.error(
                    request, 
                    "Access Denied: Only Admin and Supervisor can modify posted records."
                )
                return redirect('bevel_detail', header_id=header.id)
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
            return handle_update_bevel_consumable(request, header)
        
        if action == 'edit_time':
            return handle_edit_time_bevel_detail(request, header_id)
        
        if action == 'edit':
            return handle_edit_bevel_detail(request, header_id)

        try:
            with transaction.atomic():
                start_time_str = request.POST.get('start_time')
                stop_time_str = request.POST.get('stop_time')

                if not start_time_str or not stop_time_str:
                    messages.error(request, "Start Time dan Stop Time wajib diisi.")
                    return redirect('bevel_detail', header_id=header.id)

                try:
                    start_time = datetime.strptime(start_time_str, '%H:%M').time()
                    stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
                except ValueError:
                    messages.error(request, "Format waktu tidak valid.")
                    return redirect('bevel_detail', header_id=header.id)

                start_minutes = start_time.hour * 60 + start_time.minute
                stop_minutes = stop_time.hour * 60 + stop_time.minute

                if start_time == stop_time:
                    messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
                    return redirect('bevel_detail', header_id=header.id)

                if stop_minutes < start_minutes:
                    duration = (stop_minutes + 24 * 60) - start_minutes
                else:
                    duration = stop_minutes - start_minutes

                if duration > 24 * 60:
                    messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
                    return redirect('bevel_detail', header_id=header.id)

                bjo_id = request.POST.get('bjo')
                if not bjo_id:
                    messages.error(request, "BJO wajib dipilih.")
                    return redirect('bevel_detail', header_id=header.id)

                try:
                    bjo = JobHeader.objects.get(id=bjo_id)
                except JobHeader.DoesNotExist:
                    messages.error(request, "BJO yang dipilih tidak valid.")
                    return redirect('bevel_detail', header_id=header.id)

                job_operation = request.POST.get('job_operation', '').strip()
                if not job_operation:
                    messages.error(request, "Job Operation wajib diisi.")
                    return redirect('bevel_detail', header_id=header.id)
                
                if len(job_operation) > 3:
                    messages.error(request, "Job Operation maksimal 3 karakter.")
                    return redirect('bevel_detail', header_id=header.id)

                ct = None
                ct_str = request.POST.get('ct')
                if ct_str:
                    try:
                        ct = float(ct_str)
                        if ct < 0:
                            messages.error(request, "CT tidak boleh negatif.")
                            return redirect('bevel_detail', header_id=header.id)
                    except ValueError:
                        messages.error(request, "CT harus berupa angka.")
                        return redirect('bevel_detail', header_id=header.id)
                
                pb = None
                pb_str = request.POST.get('pb')
                if pb_str:
                    try:
                        pb = float(pb_str)
                        if pb < 0:
                            messages.error(request, "PB tidak boleh negatif.")
                            return redirect('bevel_detail', header_id=header.id)
                    except ValueError:
                        messages.error(request, "PB harus berupa angka.")
                        return redirect('bevel_detail', header_id=header.id)

                is_uncompleted = request.POST.get('is_uncompleted') == 'on'

                joint_number = request.POST.get('joint_number', '').strip()
                if not joint_number:
                    messages.error(request, "Joint Number wajib dipilih.")
                    return redirect('bevel_detail', header_id=header.id)

                # ===== HANDLE CONNECTOR NUMBER =====
                conn_number = None
                process_name = bjo.process_type.name.upper() if bjo.process_type else ''
                
                requires_connector = False
                if 'THREAD' in process_name:
                    conn_name = bjo.conn.name.upper() if bjo.conn else ''
                    valid_connections = ['XLW-S', 'XLW-GT', 'XLW']
                    requires_connector = any(vc in conn_name for vc in valid_connections)
                
                if requires_connector:
                    conn_number = request.POST.get('conn_number', '').strip()
                    if not conn_number:
                        messages.error(request, "Connector Number wajib diisi untuk BJO dengan connection XLW-S, XLW-GT, atau XLW.")
                        return redirect('bevel_detail', header_id=header.id)
                    
                    joint_exists = SerialNumber.objects.filter(
                        bjo=bjo,
                        joint_number=joint_number
                    ).exists()
                    
                    if not joint_exists:
                        box_exists = BoxProtector.objects.filter(
                            bjo=bjo,
                            serial_number=joint_number
                        ).exists()
                        
                        pin_exists = PinProtector.objects.filter(
                            bjo=bjo,
                            serial_number=joint_number
                        ).exists()
                        
                        if not box_exists and not pin_exists:
                            messages.error(
                                request,
                                f"Joint Number '{joint_number}' tidak ditemukan pada BJO '{bjo.bjo}'."
                            )
                            return redirect('bevel_detail', header_id=header.id)
                    
                    existing_connector = Connector.objects.filter(
                        bjo=bjo,
                        joint_number=joint_number
                    ).first()
                    
                    if existing_connector:
                        conn_number = existing_connector.conn_number

                def detect_bjo_type(bjo):
                    bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
                    product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
                    process_name = bjo.process_type.name.upper() if bjo.process_type else ''
                    
                    if bjo_for:
                        if 'BOX' in bjo_for:
                            return 'box'
                        elif 'PIN' in bjo_for:
                            return 'pin'
                        elif 'PIPE' in bjo_for or 'BEVEL' in bjo_for:
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

                # Cek remaining qty
                from decimal import Decimal
                total_finished = jobDetail.objects.filter(job=bjo).aggregate(
                    total=Sum('finished')
                )['total'] or Decimal(0)
                remaining_qty = float(bjo.qty) - float(total_finished)

                required_qty = 0.5 if is_uncompleted else 1.0
                qty_check_message = "0.5" if is_uncompleted else "1"

                if remaining_qty < required_qty:
                    messages.error(request, f"Remaining quantity BJO {bjo.bjo} tidak mencukupi ({remaining_qty}). Minimal dibutuhkan {qty_check_message} untuk beveling.")
                    return redirect('bevel_detail', header_id=header.id)

                protector_type = None
                is_rework = False
                is_merge_rework = False
                is_completing_uncompleted = False
                rework_detail = None
                uncompleted_detail = None
                uncompleted_same_header = False

                # ===== DETEKSI TIPE PROTECTOR DAN VALIDASI =====
                if bjo_type == 'box':
                    try:
                        protector = BoxProtector.objects.get(serial_number=joint_number, bjo=bjo)
                        protector_type = 'box'
                        
                        existing_uncompleted = BevelDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo,
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                            
                        elif protector.is_beveled and protector.is_ncr and not protector.is_rwk:
                            existing_detail_same_header = BevelDetail.objects.filter(
                                Reff=header,
                                joint_number=joint_number,
                                bjo=bjo,
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
                        elif protector.is_beveled and protector.is_rwk:
                            messages.error(request, f"BOX Protector '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                            return redirect('bevel_detail', header_id=header.id)
                        elif protector.is_beveled and not protector.is_ncr and not existing_uncompleted:
                            messages.error(request, f"BOX Protector '{joint_number}' sudah pernah di-bevel dan bukan NCR.")
                            return redirect('bevel_detail', header_id=header.id)
                            
                    except BoxProtector.DoesNotExist:
                        messages.error(request, f"BOX Protector '{joint_number}' tidak ditemukan.")
                        return redirect('bevel_detail', header_id=header.id)
                        
                elif bjo_type == 'pin':
                    try:
                        protector = PinProtector.objects.get(serial_number=joint_number, bjo=bjo)
                        protector_type = 'pin'
                        
                        existing_uncompleted = BevelDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo,
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                            
                        elif protector.is_beveled and protector.is_ncr and not protector.is_rwk:
                            existing_detail_same_header = BevelDetail.objects.filter(
                                Reff=header,
                                joint_number=joint_number,
                                bjo=bjo,
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
                        elif protector.is_beveled and protector.is_rwk:
                            messages.error(request, f"PIN Protector '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                            return redirect('bevel_detail', header_id=header.id)
                        elif protector.is_beveled and not protector.is_ncr and not existing_uncompleted:
                            messages.error(request, f"PIN Protector '{joint_number}' sudah pernah di-bevel dan bukan NCR.")
                            return redirect('bevel_detail', header_id=header.id)
                            
                    except PinProtector.DoesNotExist:
                        messages.error(request, f"PIN Protector '{joint_number}' tidak ditemukan.")
                        return redirect('bevel_detail', header_id=header.id)
                        
                else:
                    # ===== PIPE LOGIC =====
                    try:
                        serial = SerialNumber.objects.get(joint_number=joint_number, bjo=bjo)
                        protector_type = 'pipe'
                        
                        existing_uncompleted = BevelDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo,
                            is_uncompleted=True
                        ).first()
                        
                        if existing_uncompleted and not is_uncompleted:
                            is_completing_uncompleted = True
                            uncompleted_detail = existing_uncompleted
                            uncompleted_same_header = (existing_uncompleted.Reff.id == header.id)
                        else:
                            existing_detail = BevelDetail.objects.filter(
                                joint_number=joint_number,
                                bjo=bjo,
                                is_uncompleted=False
                            ).order_by('-id').first()
                            
                            if existing_detail:
                                if serial.is_rwk:
                                    messages.error(request, f"Joint '{joint_number}' sudah pernah di-rework. Tidak dapat di-rework lagi.")
                                    return redirect('bevel_detail', header_id=header.id)
                                
                                has_existing_ncr = BevelNcr.objects.filter(serial=existing_detail).exists()
                                
                                if has_existing_ncr:
                                    if existing_detail.Reff == header:
                                        is_rework = True
                                        is_merge_rework = True
                                        rework_detail = existing_detail
                                    else:
                                        is_rework = True
                                        is_merge_rework = False
                                        SerialNumber.objects.filter(
                                            joint_number=joint_number, 
                                            bjo=bjo
                                        ).update(is_rwk=True)
                                else:
                                    messages.error(request, f"Joint '{joint_number}' sudah diinput dan bukan NCR.")
                                    return redirect('bevel_detail', header_id=header.id)
                        
                    except SerialNumber.DoesNotExist:
                        messages.error(request, f"Joint Number '{joint_number}' tidak ditemukan untuk BJO yang dipilih.")
                        return redirect('bevel_detail', header_id=header.id)

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
                        uncompleted_detail.conn_no = conn_number
                        uncompleted_detail.save()
                        
                        try:
                            job_detail = jobDetail.objects.filter(
                                job=bjo,
                                remarks__icontains=f"beveling for {joint_number}"
                            ).first()
                            
                            if job_detail:
                                job_detail.finished = Decimal('1.0')
                                job_detail.remarks = job_detail.remarks.replace('UNCOMPLETED', 'COMPLETED')
                                job_detail.save()
                            else:
                                auto_remarks = f"Auto: beveling for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
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
                            ).update(is_beveled=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_beveled=True)
                        
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if not existing_connector:
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        messages.success(
                            request, 
                            f"Beveling UNCOMPLETED berhasil di-COMPLETE untuk joint '{joint_number}' (MERGED di header yang sama). "
                            f"Output: {calculated_output}. Job detail telah diupdate menjadi complete dengan finished +0.5."
                        )
                        
                        return redirect('bevel_detail', header_id=header.id)
                    
                    else:
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
                        
                        bevel_detail = BevelDetail.objects.create(
                            Reff=header,
                            start_time=start_time,
                            stop_time=stop_time,
                            bjo=bjo,
                            job_operation=job_operation,
                            ct=ct,
                            pb=pb,
                            joint_number=joint_number,
                            is_uncompleted=False,
                            output=new_calculated_output,
                            comment=new_comment,
                            conn_no=conn_number,
                        )
                        
                        try:
                            finished_value = Decimal('0.5')
                            auto_remarks = f"Auto: beveling COMPLETION for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} (from Header #{uncompleted_detail.Reff.id})"
                            if comment:
                                auto_remarks += f" | {comment}"
                            
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
                            print(f"Warning: Gagal membuat jobDetail completion: {str(job_error)}")
                        
                        if protector_type == 'box':
                            BoxProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_beveled=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_beveled=True)
                        
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if not existing_connector:
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        messages.success(
                            request, 
                            f"Beveling UNCOMPLETED berhasil di-COMPLETE untuk joint '{joint_number}' (BARU di header berbeda). "
                            f"Output record lama: {old_calculated_output}, Output record baru: {new_calculated_output}. "
                            f"Job detail created dengan finished +0.5. "
                            f"Comment uncompleted di Header #{uncompleted_detail.Reff.id} telah diupdate dengan info completion."
                        )
                        
                        return redirect('bevel_detail', header_id=header.id)

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
                    rework_detail.conn_no = conn_number
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
                    
                    BevelNcr.objects.filter(
                        serial=rework_detail,
                        reason__isnull=True
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    BevelNcr.objects.filter(
                        serial=rework_detail,
                        reason__exact=''
                    ).update(reason="REWORKED - Issue resolved through rework process")
                    
                    BevelNcr.objects.filter(
                        serial=rework_detail,
                        disposition__isnull=True
                    ).update(disposition="REWORK")
                    
                    BevelNcr.objects.filter(
                        serial=rework_detail,
                        action__isnull=True
                    ).update(action="Beveling rework performed")
                    BevelNcr.objects.filter(
                        serial=rework_detail,
                        action__exact=''
                    ).update(action="Beveling rework completed")
                    
                    if requires_connector and conn_number:
                        existing_connector = Connector.objects.filter(
                            bjo=bjo,
                            joint_number=joint_number
                        ).first()
                        
                        if not existing_connector:
                            Connector.objects.create(
                                bjo=bjo,
                                joint_number=joint_number,
                                conn_number=conn_number
                            )
                    
                    messages.success(
                        request, 
                        f"Beveling detail REWORK berhasil di-merge dengan record existing untuk joint '{joint_number}'. "
                        f"Output: {calculated_output}. Status NCR telah diupdate menjadi complete."
                    )
                    
                else:
                    # ========== CREATE NEW BEVEL DETAIL ==========
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
                    
                    bevel_detail = BevelDetail.objects.create(
                        Reff=header,
                        start_time=start_time,
                        stop_time=stop_time,
                        bjo=bjo,
                        job_operation=job_operation,
                        ct=ct,
                        pb=pb,
                        joint_number=joint_number,
                        is_uncompleted=is_uncompleted,
                        output=calculated_output,
                        comment=comment if comment else None,
                        conn_no=conn_number,
                    )

                    if not is_rework:
                        finished_value = Decimal('0.5') if is_uncompleted else Decimal('1.0')
                        
                        uncompleted_marker = " [UNCOMPLETED]" if is_uncompleted else ""
                        auto_remarks = f"Auto: beveling for {joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')}{uncompleted_marker}"
                        if comment and not comment.startswith('REWORKED') and not comment.startswith('UNCOMPLETED'):
                            auto_remarks += f" | {comment}"
                        
                        jobDetail.objects.create(
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
                            BevelNcr.objects.create(
                                serial=bevel_detail,
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
                            
                            if requires_connector and conn_number:
                                existing_connector = Connector.objects.filter(
                                    bjo=bjo,
                                    joint_number=joint_number
                                ).first()
                                
                                if not existing_connector:
                                    Connector.objects.create(
                                        bjo=bjo,
                                        joint_number=joint_number,
                                        conn_number=conn_number
                                    )
                            
                            uncompleted_status = " (UNCOMPLETED - output 0.5)" if is_uncompleted else ""
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            
                            messages.warning(
                                request, 
                                f"Beveling detail berhasil ditambahkan{uncompleted_status}. "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"NCR record telah dibuat untuk joint '{joint_number}'. "
                                "Silakan hubungi engineer untuk melengkapi detail NCR."
                            )
                            
                        except Exception as ncr_error:
                            uncompleted_status = " (UNCOMPLETED - output 0.5)" if is_uncompleted else ""
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            
                            messages.warning(
                                request,
                                f"Beveling detail berhasil ditambahkan{uncompleted_status}. "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"Namun gagal membuat NCR record: {str(ncr_error)}"
                            )
                            
                    elif is_rework and not is_merge_rework:
                        other_detail = BevelDetail.objects.filter(
                            joint_number=joint_number,
                            bjo=bjo
                        ).exclude(Reff=header).first()
                        
                        if other_detail:
                            BevelNcr.objects.filter(
                                serial=other_detail,
                                reason__isnull=True
                            ).update(reason="REWORKED in different header - Issue resolved")
                            
                            BevelNcr.objects.filter(
                                serial=other_detail,
                                reason__exact=''
                            ).update(reason="REWORKED in different header - Issue resolved")
                        
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if not existing_connector:
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        messages.success(
                            request, 
                            f"Beveling detail REWORK berhasil ditambahkan untuk joint '{joint_number}'. "
                            f"Output: {calculated_output}. Status NCR di header original telah diupdate."
                        )
                    else:
                        if requires_connector and conn_number:
                            existing_connector = Connector.objects.filter(
                                bjo=bjo,
                                joint_number=joint_number
                            ).first()
                            
                            if not existing_connector:
                                Connector.objects.create(
                                    bjo=bjo,
                                    joint_number=joint_number,
                                    conn_number=conn_number
                                )
                        
                        if is_uncompleted:
                            job_detail_info = f"Job detail otomatis dibuat dengan finished={finished_value}."
                            
                            messages.warning(
                                request, 
                                f"Beveling detail UNCOMPLETED berhasil ditambahkan (output 0.5). "
                                f"{job_detail_info} Output: {calculated_output}. "
                                f"Item ini masih bisa diselect lagi untuk melengkapinya."
                            )
                        else:
                            messages.success(
                                request, 
                                f"Beveling detail berhasil ditambahkan. "
                                f"Job detail otomatis dibuat dengan finished={finished_value}. Output: {calculated_output}."
                            )

                    if not is_rework and not is_uncompleted:
                        if protector_type == 'box':
                            BoxProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_beveled=True)
                        elif protector_type == 'pin':
                            PinProtector.objects.filter(
                                serial_number=joint_number, 
                                bjo=bjo
                            ).update(is_beveled=True)
                        else:
                            SerialNumber.objects.filter(
                                joint_number=joint_number,
                                bjo=bjo
                            ).update(is_beveled=True)

                return redirect('bevel_detail', header_id=header.id)

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('bevel_detail', header_id=header.id)

    # ========== GET METHOD - TAMPILKAN DATA ==========
    detail_list = BevelDetail.objects.filter(Reff=header).order_by('id')
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
            detail.ncr_count = BevelNcr.objects.filter(serial=detail).count()
            detail.has_ncr = detail.ncr_count > 0
            
            detail.has_incomplete_ncr = BevelNcr.objects.filter(
                serial=detail,
                reason__isnull=True
            ).exists() or BevelNcr.objects.filter(
                serial=detail,
                reason__exact=''
            ).exists()
            
        except:
            detail.ncr_count = 0
            detail.has_ncr = False
            detail.has_incomplete_ncr = False

    existing_consumable = BevelConsumsion.objects.filter(Reff=header).first()

    def detect_bjo_type(bjo):
        bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
        product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
        process_name = bjo.process_type.name.upper() if bjo.process_type else ''
        
        if bjo_for:
            if 'BOX' in bjo_for:
                return 'box'
            elif 'PIN' in bjo_for:
                return 'pin'
            elif 'PIPE' in bjo_for or 'BEVEL' in bjo_for:
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

    # Filter BJO yang masih available untuk beveling
    job_list = []
    for job in JobHeader.objects.filter(is_finish__in=[False, None]).order_by('bjo'):
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
    return render(request, 'bevel/detail.html', context)


@beveling_write_access_required
def handle_update_bevel_consumable(request, header):
    """Handle update consumable data untuk beveling"""
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit consumable data on posted records.'
            )
            return redirect('bevel_detail', header_id=header.id)
        else:
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan consumable."
            )
    
    try:
        insert_snmg = request.POST.get("insert_snmg", 0)
        insert_dnmg = request.POST.get("insert_dnmg", 0)
        insert_bevel = request.POST.get("insert_bevel", 0)
        consumable_others = request.POST.get("consumable_others", 0)

        existing_consumable = BevelConsumsion.objects.filter(Reff=header).first()

        consumable_data = {
            'insert_snmg': float(insert_snmg or 0),
            'insert_dnmg': float(insert_dnmg or 0),
            'insert_bevel': float(insert_bevel or 0),
            'others': float(consumable_others or 0),
        }

        if existing_consumable:
            for key, value in consumable_data.items():
                setattr(existing_consumable, key, value)
            existing_consumable.save()
            messages.success(request, "Data consumable berhasil diupdate.")
        else:
            consumable_data['Reff'] = header
            BevelConsumsion.objects.create(**consumable_data)
            messages.success(request, "Data consumable berhasil disimpan.")

        return redirect('bevel_detail', header_id=header.id)

    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menyimpan data consumable: {str(e)}")
        return redirect('bevel_detail', header_id=header.id)


def get_bevel_joint_numbers(request):
    """Get available joint numbers for beveling"""
    bjo_id = request.GET.get('bjo_id')
    
    if not bjo_id:
        return JsonResponse({'joint_numbers': []})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        joint_list = []
        
        def detect_bjo_type(bjo):
            bjo_for = getattr(bjo, 'bjo_for', '').upper() if hasattr(bjo, 'bjo_for') else ''
            product = getattr(bjo, 'product', '').upper() if hasattr(bjo, 'product') else ''
            process_name = bjo.process_type.name.upper() if bjo.process_type else ''
            
            if bjo_for:
                if 'BOX' in bjo_for:
                    return 'box'
                elif 'PIN' in bjo_for:
                    return 'pin'
                elif 'PIPE' in bjo_for or 'BEVEL' in bjo_for:
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
                Q(is_beveled=False) | 
                (Q(is_beveled=True) & Q(is_rwk=False))
            ).order_by('serial_number')
            
            uncompleted_protectors_list = []
            all_uncompleted = BevelDetail.objects.filter(
                bjo=bjo,
                is_uncompleted=True
            ).values_list('joint_number', flat=True).distinct()
            
            for joint_num in all_uncompleted:
                has_completed = BevelDetail.objects.filter(
                    joint_number=joint_num,
                    bjo=bjo,
                    is_uncompleted=False
                ).exists()
                
                if not has_completed:
                    uncompleted_protectors_list.append(joint_num)
            
            uncompleted_protector_numbers = uncompleted_protectors_list
            
            for protector in protectors:
                status = 'normal'
                
                if protector.serial_number in uncompleted_protector_numbers:
                    status = 'uncompleted'
                
                elif protector.is_beveled and not protector.is_rwk:
                    existing_detail = BevelDetail.objects.filter(
                        joint_number=protector.serial_number,
                        bjo=bjo,
                        is_uncompleted=False
                    ).first()
                    
                    if existing_detail:
                        has_ncr = BevelNcr.objects.filter(serial=existing_detail).exists()
                        
                        if has_ncr:
                            status = 'rework'
                        else:
                            continue
                    else:
                        continue
                
                elif not protector.is_beveled:
                    status = 'normal'
                elif protector.is_rwk:
                    continue
                
                joint_list.append({
                    'joint_number': protector.serial_number,
                    'type': 'box_protector',
                    'status': status,
                    'is_rework': status == 'rework',
                    'is_uncompleted': status == 'uncompleted',
                    'rework_info': {
                        'is_ncr': protector.is_ncr,
                        'is_rwk': protector.is_rwk,
                        'is_beveled': protector.is_beveled
                    }
                })
            
            for uncompleted_joint in uncompleted_protector_numbers:
                if not any(j['joint_number'] == uncompleted_joint for j in joint_list):
                    protector = BoxProtector.objects.filter(serial_number=uncompleted_joint, bjo=bjo).first()
                    if protector:
                        joint_list.append({
                            'joint_number': protector.serial_number,
                            'type': 'box_protector',
                            'status': 'uncompleted',
                            'is_rework': False,
                            'is_uncompleted': True,
                            'rework_info': {
                                'is_ncr': protector.is_ncr,
                                'is_rwk': protector.is_rwk,
                                'is_beveled': protector.is_beveled
                            }
                        })
                    
        elif bjo_type == 'pin':
            # ===== PIN PROTECTOR LOGIC =====
            protectors = PinProtector.objects.filter(bjo=bjo).filter(
                Q(is_beveled=False) | 
                (Q(is_beveled=True) & Q(is_rwk=False))
            ).order_by('serial_number')
            
            uncompleted_protectors_list = []
            all_uncompleted = BevelDetail.objects.filter(
                bjo=bjo,
                is_uncompleted=True
            ).values_list('joint_number', flat=True).distinct()
            
            for joint_num in all_uncompleted:
                has_completed = BevelDetail.objects.filter(
                    joint_number=joint_num,
                    bjo=bjo,
                    is_uncompleted=False
                ).exists()
                
                if not has_completed:
                    uncompleted_protectors_list.append(joint_num)
            
            uncompleted_protector_numbers = uncompleted_protectors_list
            
            for protector in protectors:
                status = 'normal'
                
                if protector.serial_number in uncompleted_protector_numbers:
                    status = 'uncompleted'
                
                elif protector.is_beveled and not protector.is_rwk:
                    existing_detail = BevelDetail.objects.filter(
                        joint_number=protector.serial_number,
                        bjo=bjo,
                        is_uncompleted=False
                    ).first()
                    
                    if existing_detail:
                        has_ncr = BevelNcr.objects.filter(serial=existing_detail).exists()
                        
                        if has_ncr:
                            status = 'rework'
                        else:
                            continue
                    else:
                        continue
                
                elif not protector.is_beveled:
                    status = 'normal'
                elif protector.is_rwk:
                    continue
                
                joint_list.append({
                    'joint_number': protector.serial_number,
                    'type': 'pin_protector',
                    'status': status,
                    'is_rework': status == 'rework',
                    'is_uncompleted': status == 'uncompleted',
                    'rework_info': {
                        'is_ncr': protector.is_ncr,
                        'is_rwk': protector.is_rwk,
                        'is_beveled': protector.is_beveled
                    }
                })
            
            for uncompleted_joint in uncompleted_protector_numbers:
                if not any(j['joint_number'] == uncompleted_joint for j in joint_list):
                    protector = PinProtector.objects.filter(serial_number=uncompleted_joint, bjo=bjo).first()
                    if protector:
                        joint_list.append({
                            'joint_number': protector.serial_number,
                            'type': 'pin_protector',
                            'status': 'uncompleted',
                            'is_rework': False,
                            'is_uncompleted': True,
                            'rework_info': {
                                'is_ncr': protector.is_ncr,
                                'is_rwk': protector.is_rwk,
                                'is_beveled': protector.is_beveled
                            }
                        })
        
        else:  # PIPE BJO
            # ===== PIPE LOGIC =====
            serials = SerialNumber.objects.filter(bjo=bjo).order_by('joint_number')

            for serial in serials:
                # Cek apakah sudah ada beveling
                any_beveling = BevelDetail.objects.filter(
                    joint_number=serial.joint_number,
                    bjo=bjo
                ).exists()
                
                # Cek status UNCOMPLETED
                has_uncompleted = BevelDetail.objects.filter(
                    joint_number=serial.joint_number,
                    bjo=bjo,
                    is_uncompleted=True
                ).exists()
                
                has_completed = BevelDetail.objects.filter(
                    joint_number=serial.joint_number,
                    bjo=bjo,
                    is_uncompleted=False
                ).exists()
                
                is_uncompleted = has_uncompleted and not has_completed
                
                # Logika untuk menentukan status
                if is_uncompleted:
                    status = 'uncompleted'
                elif any_beveling and has_completed:
                    # Cek apakah ada NCR
                    latest_detail = BevelDetail.objects.filter(
                        joint_number=serial.joint_number,
                        bjo=bjo,
                        is_uncompleted=False
                    ).order_by('-id').first()
                    
                    has_ncr = BevelNcr.objects.filter(serial=latest_detail).exists() if latest_detail else False
                    is_already_reworked = serial.is_rwk
                    
                    if has_ncr and not is_already_reworked:
                        status = 'rework'
                    else:
                        continue  # Skip - sudah selesai
                else:
                    status = 'normal'
                
                joint_list.append({
                    'joint_number': serial.joint_number,
                    'type': 'pipe',
                    'status': status,
                    'is_rework': status == 'rework',
                    'is_uncompleted': status == 'uncompleted',
                    'rework_info': {
                        'is_ncr': serial.is_ncr,
                        'is_rwk': serial.is_rwk,
                        'any_beveling': any_beveling
                    }
                })

        return JsonResponse({'joint_numbers': joint_list})

    except JobHeader.DoesNotExist:
        return JsonResponse({'joint_numbers': []})
    except Exception as e:
        return JsonResponse({'joint_numbers': [], 'error': str(e)})


@beveling_detail_edit_access_required
def handle_edit_bevel_detail(request, header_id):
    """Handle edit beveling detail with NCR auto-creation/deletion"""
    header = get_object_or_404(BevelHeader, pk=header_id)
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit details on posted records.'
            )
            return redirect('bevel_detail', header_id=header.id)
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
        return redirect('bevel_detail', header_id=header.id)
    
    try:
        detail = BevelDetail.objects.get(id=detail_id, Reff=header)
        old_comment = detail.comment or ''
        old_is_uncompleted = detail.is_uncompleted
        old_output = detail.output
    except BevelDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('bevel_detail', header_id=header.id)
    
    try:
        start_time_str = request.POST.get('start_time')
        stop_time_str = request.POST.get('stop_time')
        
        if not start_time_str or not stop_time_str:
            messages.error(request, "Start Time dan Stop Time wajib diisi.")
            return redirect('bevel_detail', header_id=header.id)
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            stop_time = datetime.strptime(stop_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format waktu tidak valid.")
            return redirect('bevel_detail', header_id=header.id)
        
        start_minutes = start_time.hour * 60 + start_time.minute
        stop_minutes = stop_time.hour * 60 + stop_time.minute

        if start_time == stop_time:
            messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
            return redirect('bevel_detail', header_id=header.id)

        if stop_minutes < start_minutes:
            duration = (stop_minutes + 24 * 60) - start_minutes
        else:
            duration = stop_minutes - start_minutes

        if duration > 24 * 60:
            messages.error(request, "Durasi kerja tidak boleh lebih dari 24 jam.")
            return redirect('bevel_detail', header_id=header.id)
        
        job_operation = request.POST.get('job_operation', '').strip()
        if not job_operation:
            messages.error(request, "Job Operation wajib diisi.")
            return redirect('bevel_detail', header_id=header.id)
        
        if len(job_operation) > 3:
            messages.error(request, "Job Operation maksimal 3 karakter.")
            return redirect('bevel_detail', header_id=header.id)
        
        ct = None
        ct_str = request.POST.get('ct')
        if ct_str:
            try:
                ct = float(ct_str)
                if ct < 0:
                    messages.error(request, "CT tidak boleh negatif.")
                    return redirect('bevel_detail', header_id=header.id)
            except ValueError:
                messages.error(request, "CT harus berupa angka.")
                return redirect('bevel_detail', header_id=header.id)
        
        pb = None
        pb_str = request.POST.get('pb')
        if pb_str:
            try:
                pb = float(pb_str)
                if pb < 0:
                    messages.error(request, "PB tidak boleh negatif.")
                    return redirect('bevel_detail', header_id=header.id)
            except ValueError:
                messages.error(request, "PB harus berupa angka.")
                return redirect('bevel_detail', header_id=header.id)
        
        # Handle UNCOMPLETED status toggle
        toggle_status = request.POST.get('toggle_status')
        
        if toggle_status is not None:
            new_is_uncompleted = request.POST.get('is_uncompleted') == 'on'
        else:
            new_is_uncompleted = old_is_uncompleted
        
        comment = request.POST.get('comment', '').strip()
        
        # Initialize calculated_output dengan nilai lama
        calculated_output = old_output
        
        # Handle perubahan status UNCOMPLETED
        if old_is_uncompleted != new_is_uncompleted:
            calculated_output = 0.5 if new_is_uncompleted else 1.0
            
            bjo = detail.bjo
            bjo.refresh_from_db()
            
            from decimal import Decimal
            
            if new_is_uncompleted and not old_is_uncompleted:
                # COMPLETE → UNCOMPLETED
                qty_adjustment = 0.5
                finished_old = Decimal('1.0')
                finished_new = Decimal('0.5')
                
                bjo.qty = float(bjo.qty) + qty_adjustment
                bjo.save()
                
                job_detail = jobDetail.objects.filter(
                    job=bjo,
                    remarks__icontains=f"beveling for {detail.joint_number}",
                    finished=finished_old
                ).first()
                
                if job_detail:
                    job_detail.finished = finished_new
                    if '[UNCOMPLETED]' not in job_detail.remarks:
                        job_detail.remarks = job_detail.remarks.replace('[COMPLETED]', '').strip()
                        job_detail.remarks += " [UNCOMPLETED]"
                    job_detail.save()
                
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
                # UNCOMPLETED → COMPLETE
                existing_uncompleted_same_header = BevelDetail.objects.filter(
                    Reff=header,
                    joint_number=detail.joint_number,
                    bjo=bjo,
                    is_uncompleted=True
                ).exclude(id=detail.id).first()
                
                if existing_uncompleted_same_header:
                    # MERGE
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
                    existing_uncompleted_same_header.save()
                    
                    detail.delete()
                    
                    qty_adjustment = 0.5
                    finished_old = Decimal('0.5')
                    finished_new = Decimal('1.0')
                    
                    bjo.qty = float(bjo.qty) - qty_adjustment
                    if bjo.qty < 0:
                        bjo.qty = 0
                    bjo.save()
                    
                    job_detail = jobDetail.objects.filter(
                        job=bjo,
                        remarks__icontains=f"beveling for {detail.joint_number}",
                        finished=finished_old
                    ).first()
                    
                    if job_detail:
                        job_detail.finished = finished_new
                        job_detail.remarks = job_detail.remarks.replace('[UNCOMPLETED]', '[COMPLETED]')
                        job_detail.save()
                    else:
                        auto_remarks = f"Auto: beveling for {detail.joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_new,
                            remarks=auto_remarks,
                        )
                    
                    messages.success(
                        request,
                        f"Beveling UNCOMPLETED berhasil di-COMPLETE dan di-merge dengan record existing. "
                        f"Output: {calculated_output}. Quantity dikurangi -{qty_adjustment}"
                    )
                    
                    return redirect('bevel_detail', header_id=header.id)
                    
                else:
                    # UPDATE BIASA
                    qty_adjustment = 0.5
                    finished_old = Decimal('0.5')
                    finished_new = Decimal('1.0')
                    
                    bjo.qty = float(bjo.qty) - qty_adjustment
                    if bjo.qty < 0:
                        bjo.qty = 0
                    bjo.save()
                    
                    job_detail = jobDetail.objects.filter(
                        job=bjo,
                        remarks__icontains=f"beveling for {detail.joint_number}",
                        finished=finished_old
                    ).first()
                    
                    if job_detail:
                        job_detail.finished = finished_new
                        job_detail.remarks = job_detail.remarks.replace('[UNCOMPLETED]', '[COMPLETED]')
                        job_detail.save()
                    else:
                        auto_remarks = f"Auto: beveling for {detail.joint_number} at {start_time.strftime('%H:%M')}-{stop_time.strftime('%H:%M')} [COMPLETED]"
                        
                        jobDetail.objects.create(
                            job=bjo,
                            box=None,
                            pin=None,
                            fs=None,
                            fc=None,
                            finished=finished_new,
                            remarks=auto_remarks,
                        )
                    
                    old_comment_clean = old_comment.replace('UNCOMPLETED |', '').replace('| UNCOMPLETED', '').strip()
                    if comment:
                        comment = f"COMPLETED | {comment}"
                    else:
                        if old_comment_clean:
                            comment = f"COMPLETED | {old_comment_clean}"
                        else:
                            comment = "COMPLETED"
                    
                    messages.info(request, f"Status berubah menjadi COMPLETE. Quantity dikurangi -{qty_adjustment}")
        
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
            detail.save()
        except BevelDetail.DoesNotExist:
            pass
        
        # Handle NCR
        new_comment = comment or ''
        has_ncr_in_new = 'NCR' in new_comment.upper()
        has_ncr_in_old = 'NCR' in old_comment.upper()
        
        existing_ncr = BevelNcr.objects.filter(serial=detail).exists()
        
        if has_ncr_in_new and not has_ncr_in_old:
            if not existing_ncr:
                try:
                    BevelNcr.objects.create(serial=detail)
                    
                    # Update protector/serial status
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
                        f"Beveling detail berhasil diupdate. Output: {calculated_output}. "
                        f"NCR record telah dibuat untuk joint '{detail.joint_number}'. "
                        "Silakan hubungi engineer untuk melengkapi detail NCR."
                    )
                except Exception as ncr_error:
                    messages.warning(
                        request,
                        f"Beveling detail berhasil diupdate dengan output: {calculated_output}, "
                        f"namun gagal membuat NCR record: {str(ncr_error)}"
                    )
            else:
                messages.success(request, f"Beveling detail berhasil diupdate. Output: {calculated_output}. NCR record sudah ada sebelumnya.")
                
        elif not has_ncr_in_new and has_ncr_in_old:
            if existing_ncr:
                try:
                    BevelNcr.objects.filter(serial=detail).delete()
                    
                    # Update protector/serial status
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
                        f"Beveling detail berhasil diupdate. Output: {calculated_output}. "
                        f"NCR record telah dihapus karena comment tidak lagi mengandung 'NCR'."
                    )
                except Exception as ncr_error:
                    messages.warning(
                        request,
                        f"Beveling detail berhasil diupdate dengan output: {calculated_output}, "
                        f"namun gagal menghapus NCR record: {str(ncr_error)}"
                    )
            else:
                messages.success(request, f"Beveling detail berhasil diupdate. Output: {calculated_output}.")
                
        else:
            if old_is_uncompleted == new_is_uncompleted:
                messages.success(request, f"Beveling detail berhasil diupdate. Output: {calculated_output}.")
        
        return redirect('bevel_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('bevel_detail', header_id=header.id)

@beveling_management_access_required
def bevel_detail_delete(request, header_id):
    """Delete beveling detail dengan auto restore jobDetail"""
    header = get_object_or_404(BevelHeader, pk=header_id)
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                "Access Denied: Only Admin and Supervisor can delete details on posted records."
            )
            return redirect('bevel_detail', header_id=header.id)
        else:
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada penghapusan detail."
            )
    
    if request.method != 'POST':
        messages.error(request, "Method tidak diizinkan.")
        return redirect('bevel_detail', header_id=header.id)
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('bevel_detail', header_id=header.id)
    
    try:
        with transaction.atomic():
            detail = BevelDetail.objects.get(id=detail_id, Reff=header)
            
            joint_number = detail.joint_number
            bjo = detail.bjo
            is_rework_detail = 'REWORKED' in (detail.comment or '')
            is_uncompleted = detail.is_uncompleted
            output_value = detail.output or 0
            
            # Deteksi jenis protector/joint
            is_box_protector = BoxProtector.objects.filter(serial_number=joint_number, bjo=bjo).exists()
            is_pin_protector = PinProtector.objects.filter(serial_number=joint_number, bjo=bjo).exists()
            is_pipe = not is_box_protector and not is_pin_protector
            
            # Hapus jobDetail
            deleted_finished_value = 0
            if not is_rework_detail:
                try:
                    from decimal import Decimal
                    
                    finished_val = Decimal('0.5') if is_uncompleted else Decimal('1.0')
                    deleted_count = jobDetail.objects.filter(
                        job=bjo,
                        remarks__icontains=f"beveling for {joint_number}",
                        finished=finished_val
                    ).delete()[0]
                    
                    if deleted_count > 0:
                        deleted_finished_value = float(finished_val)
                    
                except Exception as job_detail_error:
                    print(f"Warning: Gagal menghapus jobDetail: {str(job_detail_error)}")
            
            # Hapus NCR records
            try:
                ncr_deleted = BevelNcr.objects.filter(serial=detail).delete()[0]
                if ncr_deleted > 0:
                    print(f"Info: {ncr_deleted} NCR record(s) dihapus untuk detail {detail.id}")
            except Exception as ncr_error:
                print(f"Warning: Gagal menghapus NCR records: {str(ncr_error)}")
            
            # Hapus detail
            detail.delete()
            
            # Reset status protector/SerialNumber
            if is_box_protector:
                remaining_details = BevelDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo
                ).exists()
                
                if not remaining_details:
                    BoxProtector.objects.filter(
                        serial_number=joint_number, 
                        bjo=bjo
                    ).update(is_beveled=False, is_rwk=False, is_ncr=False)
                else:
                    has_other_ncr = BevelDetail.objects.filter(
                        joint_number=joint_number,
                        bjo=bjo
                    ).exclude(id=detail_id).exists() and BevelNcr.objects.filter(
                        serial__joint_number=joint_number,
                        serial__bjo=bjo
                    ).exists()
                    
                    if is_rework_detail:
                        BoxProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=False)
                    
                    if not has_other_ncr:
                        BoxProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_ncr=False)
                        
            elif is_pin_protector:
                remaining_details = BevelDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo
                ).exists()
                
                if not remaining_details:
                    PinProtector.objects.filter(
                        serial_number=joint_number, 
                        bjo=bjo
                    ).update(is_beveled=False, is_rwk=False, is_ncr=False)
                else:
                    has_other_ncr = BevelDetail.objects.filter(
                        joint_number=joint_number,
                        bjo=bjo
                    ).exclude(id=detail_id).exists() and BevelNcr.objects.filter(
                        serial__joint_number=joint_number,
                        serial__bjo=bjo
                    ).exists()
                    
                    if is_rework_detail:
                        PinProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=False)
                    
                    if not has_other_ncr:
                        PinProtector.objects.filter(
                            serial_number=joint_number, 
                            bjo=bjo
                        ).update(is_ncr=False)
                        
            else:  # PIPE joint
                remaining_details = BevelDetail.objects.filter(
                    joint_number=joint_number,
                    bjo=bjo
                ).exists()
                
                if not remaining_details:
                    SerialNumber.objects.filter(
                        joint_number=joint_number, 
                        bjo=bjo
                    ).update(
                        is_beveled=False,
                        is_rwk=False,
                        is_ncr=False
                    )
                else:
                    if is_rework_detail:
                        SerialNumber.objects.filter(
                            joint_number=joint_number, 
                            bjo=bjo
                        ).update(is_rwk=False)
                    
                    has_other_ncr = BevelNcr.objects.filter(
                        serial__joint_number=joint_number,
                        serial__bjo=bjo
                    ).exists()
                    
                    if not has_other_ncr:
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
                    f"REWORK detail beveling untuk {joint_number} berhasil dihapus. "
                    f"Output yang dihapus: {output_value}. Status rework telah di-reset."
                )
            elif is_uncompleted:
                if deleted_finished_value > 0:
                    messages.success(
                        request, 
                        f"UNCOMPLETED detail beveling untuk {joint_number} berhasil dihapus. "
                        f"Output yang dihapus: {output_value}. JobDetail (finished: -{deleted_finished_value}) telah dihapus. "
                        f"BJO {bjo.bjo} qty tetap: {bjo.qty}. Remaining akan bertambah +{deleted_finished_value}."
                    )
                else:
                    messages.success(
                        request, 
                        f"UNCOMPLETED detail beveling untuk {joint_number} berhasil dihapus. "
                        f"Output yang dihapus: {output_value}. BJO {bjo.bjo} qty tetap: {bjo.qty}."
                    )
            else:
                messages.success(
                    request, 
                    f"Detail beveling untuk {joint_number} berhasil dihapus. "
                    f"Output yang dihapus: {output_value}. JobDetail (finished: -{deleted_finished_value}) telah dihapus. "
                    f"BJO {bjo.bjo} qty tetap: {bjo.qty}. Remaining akan bertambah +{deleted_finished_value}."
                )
                
            return redirect('bevel_detail', header_id=header.id)
            
    except BevelDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('bevel_detail', header_id=header.id)
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan saat menghapus: {str(e)}")
        return redirect('bevel_detail', header_id=header.id)


@beveling_management_access_required
def handle_edit_time_bevel_detail(request, header_id):
    """Handle edit beveling detail time only with duration-based calculation"""
    header = get_object_or_404(BevelHeader, pk=header_id)
    
    if header.is_posted:
        if request.user.role not in ['admin', 'supervisor']:
            messages.error(
                request, 
                'Access Denied: Only Admin and Supervisor can edit time on posted records.'
            )
            return redirect('bevel_detail', header_id=header.id)
        else:
            header.is_posted = False
            header.save(update_fields=['is_posted'])
            messages.warning(
                request,
                "Status record telah dikembalikan ke DRAFT karena ada perubahan waktu."
            )
    
    detail_id = request.POST.get('detail_id')
    
    if not detail_id:
        messages.error(request, "Detail ID tidak ditemukan.")
        return redirect('bevel_detail', header_id=header.id)
    
    try:
        detail = BevelDetail.objects.get(id=detail_id, Reff=header)
    except BevelDetail.DoesNotExist:
        messages.error(request, "Detail tidak ditemukan.")
        return redirect('bevel_detail', header_id=header.id)
    
    try:
        start_time_str = request.POST.get('start_time')
        duration_hours_str = request.POST.get('duration_hours')
        
        if not start_time_str or not duration_hours_str:
            messages.error(request, "Start Time dan Duration wajib diisi.")
            return redirect('bevel_detail', header_id=header.id)
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, "Format start time tidak valid.")
            return redirect('bevel_detail', header_id=header.id)
        
        try:
            duration_hours = float(duration_hours_str)
            if duration_hours <= 0:
                messages.error(request, "Duration harus lebih dari 0.")
                return redirect('bevel_detail', header_id=header.id)
            if duration_hours > 16:
                messages.error(request, "Duration maksimal 16 jam.")
                return redirect('bevel_detail', header_id=header.id)
        except ValueError:
            messages.error(request, "Format duration tidak valid.")
            return redirect('bevel_detail', header_id=header.id)
        
        # Calculate stop time
        start_datetime = datetime.combine(datetime.today(), start_time)
        stop_datetime = start_datetime + timedelta(hours=duration_hours)
        stop_time = stop_datetime.time()
        
        if start_time == stop_time:
            messages.error(request, "Stop Time tidak boleh sama dengan Start Time.")
            return redirect('bevel_detail', header_id=header.id)
        
        # Update detail
        detail.start_time = start_time
        detail.stop_time = stop_time
        detail.save()
        
        duration_display = f"{duration_hours:.1f}"
        
        messages.success(
            request, 
            f"Time berhasil diupdate. "
            f"Start: {start_time.strftime('%H:%M')}, "
            f"Duration: {duration_display} hours, "
            f"Stop: {stop_time.strftime('%H:%M')}"
        )
        
        return redirect('bevel_detail', header_id=header.id)
        
    except Exception as e:
        messages.error(request, f"Terjadi kesalahan: {str(e)}")
        return redirect('bevel_detail', header_id=header.id)


def get_bevel_ct_pb_values(request):
    """AJAX untuk mengambil nilai CT dan PB berdasarkan BJO yang dipilih untuk beveling"""
    bjo_id = request.GET.get('bjo_id')
    if not bjo_id:
        return JsonResponse({'ct': None, 'pb': None})

    try:
        bjo = JobHeader.objects.get(id=bjo_id)
        
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
    
def bevel_report(request, header_id):
    """Generate Daily Production Report for Beveling"""
    
    header = get_object_or_404(BevelHeader, pk=header_id)
    
    # Untuk shift 2 yang melewati tengah malam, adjust ordering
    detail_list = BevelDetail.objects.filter(Reff=header).annotate(
        adjusted_time=Case(
            # Jika waktu mulai antara 00:00-11:59, tambahkan 24 jam untuk sorting
            When(start_time__hour__lt=12, then=F('start_time__hour') + 24),
            default=F('start_time__hour'),
        )
    ).order_by('adjusted_time', 'start_time__minute', 'id')
    
    def calculate_actual_hours_from_details():
        """Calculate total actual working hours from details"""
        total_hours = 0
        for detail in detail_list:
            if detail.start_time and detail.stop_time:
                hours = calculate_time_duration(detail.start_time, detail.stop_time)
                if hours is not None:
                    total_hours += hours
        return total_hours
    
    actual_hours = calculate_actual_hours_from_details()
    
    # Calculate total output
    total_output = detail_list.aggregate(Sum('output'))['output__sum'] or 0
    total_output = round(float(total_output), 2)
    
    # Get reason stops and consumable data
    reason_stops = BevelReasonStop.objects.filter(Reff=header).first()
    consumable = BevelConsumsion.objects.filter(Reff=header).first()
    
    # Determine shift
    is_shift_1 = header.shift and (
        '1' in header.shift.name or 
        'satu' in header.shift.name.lower() or 
        'first' in header.shift.name.lower()
    )
    is_shift_2 = header.shift and (
        '2' in header.shift.name or 
        'dua' in header.shift.name.lower() or 
        'second' in header.shift.name.lower()
    )
    
    # Calculate maintenance duration
    maintenance_duration = 0
    maintenance_info = ""
    
    if reason_stops and reason_stops.maintenance:
        raw_duration = reason_stops.maintenance.duration
        maintenance_duration = float(raw_duration) if raw_duration else 0
        maintenance_duration = round(maintenance_duration, 1)
        
        maintenance_issue = reason_stops.maintenance.issue if reason_stops.maintenance.issue else "Maintenance"
        maintenance_info = f"{maintenance_issue} ({maintenance_duration}h)"
    
    def safe_float(value):
        """Safely convert value to float"""
        if value is None or value == '' or value == '-':
            return 0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0
    
    # Calculate all time components (round to 1 decimal)
    wait_material = round(safe_float(reason_stops.waiting_materials if reason_stops else 0), 1)
    meetings = round(safe_float(reason_stops.meeting if reason_stops else 0), 1)
    breakdown = maintenance_duration  # Already rounded to 1 decimal
    change_over = round(safe_float(reason_stops.change_over if reason_stops else 0), 1)
    
    total_non_recordable = wait_material + meetings + breakdown + change_over
    total_non_recordable = round(total_non_recordable, 1)
    
    # Get booked hours
    booked_hours = 0
    if header.booked_hours and header.booked_hours.duration:
        booked_hours = float(header.booked_hours.duration)
    booked_hours = round(booked_hours, 1)
    
    # Calculate total hours
    total_hours = actual_hours + total_non_recordable
    total_hours = round(total_hours, 1)
    
    # Round actual_hours after calculation
    actual_hours = round(actual_hours, 1)
    
    # Get reject and cutback data
    rejects = round(safe_float(reason_stops.reject if reason_stops else 0), 1)
    cutbacks = round(safe_float(reason_stops.cutback if reason_stops else 0), 1)
    
    # Process detail list - add duration and NCR status
    for detail in detail_list:
        detail.duration_minutes = calculate_time_duration(detail.start_time, detail.stop_time)
        
        # Check NCR status
        ncr_record = BevelNcr.objects.filter(serial=detail).first()
        if ncr_record:
            detail.ncr_status = "NCR"
            detail.ncr_reason = ncr_record.reason
        else:
            detail.ncr_status = "-"
            detail.ncr_reason = ""
    
    # Count total NCR
    total_ncr = sum(1 for detail in detail_list if hasattr(detail, 'ncr_status') and detail.ncr_status == "NCR")
    
    # Get daily maintenance records
    daily_maintenances = Maintenance.objects.filter(machine=header.machine)
    
    # Prepare summary data
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
    
    # Prepare consumable data
    consumable_data = {
        'insert_snmg_1': '',
        'insert_dnmg_1': '',
        'insert_bevel_1': '',
        'others_1': '',
        'insert_snmg_2': '',
        'insert_dnmg_2': '',
        'insert_bevel_2': '',
        'others_2': '',
    }
    
    if consumable:
        if is_shift_1:
            consumable_data.update({
                'insert_snmg_1': consumable.insert_snmg or '-',
                'insert_dnmg_1': consumable.insert_dnmg or '-',
                'insert_bevel_1': consumable.insert_bevel or '-',
                'others_1': consumable.others or '-',
            })
        elif is_shift_2:
            consumable_data.update({
                'insert_snmg_2': consumable.insert_snmg or '-',
                'insert_dnmg_2': consumable.insert_dnmg or '-',
                'insert_bevel_2': consumable.insert_bevel or '-',
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
    
    return render(request, 'bevel/report.html', context)

@beveling_management_access_required
def finalisasi_bevel(request, pk):
    """Finalize beveling record with reason stops and maintenance"""
    header = get_object_or_404(BevelHeader, pk=pk)

    def calculate_totals():
        """Helper function to calculate total hours, qty, and auto values for actual fields"""
        detail_qs = BevelDetail.objects.filter(Reff=header)

        # Calculate total hours
        total_hours = 0
        for d in detail_qs:
            if d.start_time and d.stop_time:
                duration_hours = calculate_time_duration(d.start_time, d.stop_time)
                if duration_hours:
                    total_hours += duration_hours

        # Calculate total_qty from SUM of output
        total_qty = detail_qs.aggregate(Sum('output'))['output__sum'] or 0
        total_qty = round(total_qty, 2)
        
        # actual_output follows total_qty
        actual_output = total_qty
        
        # actual_hours follows total_hours
        actual_hours = round(total_hours, 2)
        
        return total_qty, total_hours, actual_output, actual_hours

    # Get all unique BJOs in this shift
    bjos_in_shift = BevelDetail.objects.filter(Reff=header).values_list('bjo', flat=True).distinct()
    bjos_list = JobHeader.objects.filter(id__in=bjos_in_shift)
    
    # Prepare BJO data with existing reason stops
    bjos_data = []
    for bjo in bjos_list:
        # Use .first() to avoid MultipleObjectsReturned
        reason_stop = BevelReasonStop.objects.filter(Reff=header, bjo=bjo).first()
        bjos_data.append({
            'id': bjo.id,
            'bjo': bjo.bjo,
            'customer': bjo.customer,
            'size': bjo.size,
            'qty': bjo.qty,
            'reject': reason_stop.reject if reason_stop and reason_stop.reject else 0,
            'cutback': reason_stop.cutback if reason_stop and reason_stop.cutback else 0,
            'change_over': reason_stop.change_over if reason_stop and reason_stop.change_over else 0,
            'change_over_comment': reason_stop.change_over_comment if reason_stop else '',
        })
    
    # Get existing shared reason stop
    existing_shared_reason_stop = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
    
    # Load existing maintenance data if any - ✅ UPDATE INI
    existing_maintenance = Maintenance.objects.filter(bevel_machine=header).first()

    # Initial calculation
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

        # Validate details
        if total_qty == 0:
            messages.error(request, "Cannot complete finalization because details are still empty.")
            return redirect("bevel_detail", header_id=header.pk)

        if not actual_output or not actual_hours:
            messages.error(request, "Actual Output and Actual Hours are required.")
            return render(request, "bevel/final.html", {
                "header": header,
                "total_qty": total_qty,
                "total_hours": round(total_hours, 2),
                "booked_duration": booked_duration,
                "time_difference": 0,
                "need_reason_explanation": False,
                "is_overtime": False,
                "bjos_data": bjos_data,
                "existing_shared_reason_stop": existing_shared_reason_stop,
                "existing_maintenance": existing_maintenance,
                "auto_actual_output": auto_actual_output,
                "auto_actual_hours": auto_actual_hours,
            })

        time_difference = booked_duration - actual_hours_float

        # Check if overtime or undertime
        if time_difference < -0.0167:  # Overtime detected
            is_overtime = True
            time_difference = abs(time_difference)
            need_reason_explanation = True
        elif time_difference > 0.0167:  # Undertime (remaining time)
            is_overtime = False
            need_reason_explanation = True
        else:  # Perfect match
            is_overtime = False
            need_reason_explanation = False

        # Handle reason stop logic
        if need_reason_explanation:
            # === SHARED REASON STOPS ===
            waiting_materials_shared = request.POST.get("waiting_materials_shared", 0)
            meeting_shared = request.POST.get("meeting_shared", 0)
            others_shared = request.POST.get("others_shared", 0)
            
            maintenance_duration = request.POST.get("maintenance_duration", 0)
            maintenance_cost = request.POST.get("maintenance_cost", 0)
            maintenance_issue = request.POST.get("maintenance_issue", "").strip()

            # Calculate total from shared
            total_shared_time = (
                float(waiting_materials_shared or 0) + 
                float(meeting_shared or 0) + 
                float(others_shared or 0) +
                float(maintenance_duration or 0)
            )
            
            # === PER BJO REASON STOPS ===
            total_per_bjo_time = 0
            bjo_reason_data = {}
            
            for bjo_data in bjos_data:
                bjo_id = bjo_data['id']
                reject = request.POST.get(f"reject_{bjo_id}", 0)
                cutback = request.POST.get(f"cutback_{bjo_id}", 0)
                change_over = request.POST.get(f"change_over_{bjo_id}", 0)
                change_over_comment = request.POST.get(f"change_over_comment_{bjo_id}", "").strip()
                
                total_per_bjo_time += float(change_over or 0)
                
                bjo_reason_data[bjo_id] = {
                    'reject': int(reject or 0),
                    'cutback': int(cutback or 0),
                    'change_over': float(change_over or 0),
                    'change_over_comment': change_over_comment,
                }
            
            # Total all reason times
            total_reason_time = total_shared_time + total_per_bjo_time

            # Validation: must match time_difference
            reason_type = "overtime" if is_overtime else "remaining time"
            if abs(total_reason_time - time_difference) > 0.0167:
                messages.error(
                    request, 
                    f"Total reason stop time ({total_reason_time:.2f} hours) MUST MATCH "
                    f"{reason_type} ({time_difference:.2f} hours). "
                    f"Cannot be more or less! "
                    f"(Shared: {total_shared_time:.2f} hrs + Per BJO: {total_per_bjo_time:.2f} hrs)"
                )
                return render(request, "bevel/final.html", {
                    "header": header,
                    "total_qty": total_qty,
                    "total_hours": round(total_hours, 2),
                    "booked_duration": booked_duration,
                    "time_difference": round(time_difference, 2),
                    "need_reason_explanation": need_reason_explanation,
                    "is_overtime": is_overtime,
                    "bjos_data": bjos_data,
                    "existing_shared_reason_stop": existing_shared_reason_stop,
                    "existing_maintenance": existing_maintenance,
                    "actual_output": actual_output,
                    "actual_hours": actual_hours,
                    "auto_actual_output": auto_actual_output,
                    "auto_actual_hours": auto_actual_hours,
                })

            # ✅ UPDATE/CREATE MAINTENANCE untuk BEVEL
            maintenance_obj = None
            maintenance_duration_float = float(maintenance_duration or 0)
            
            if maintenance_duration_float > 0:
                maintenance_issue_final = maintenance_issue if maintenance_issue else f"Maintenance - {header.machine.name}"
                maintenance_cost_final = float(maintenance_cost or 0)
                
                try:
                    # Cari existing maintenance untuk bevel_machine ini
                    existing_maintenance_obj = Maintenance.objects.filter(bevel_machine=header).first()
                    
                    if existing_maintenance_obj:
                        # UPDATE existing
                        existing_maintenance_obj.duration = maintenance_duration_float
                        existing_maintenance_obj.cost = maintenance_cost_final
                        existing_maintenance_obj.issue = maintenance_issue_final
                        existing_maintenance_obj.save()
                        maintenance_obj = existing_maintenance_obj
                    else:
                        # CREATE baru jika belum ada
                        maintenance_obj = Maintenance.objects.create(
                            bevel_machine=header,  # ✅ GANTI dari machine ke bevel_machine
                            issue=maintenance_issue_final,
                            duration=maintenance_duration_float,
                            cost=maintenance_cost_final
                        )
                        
                except Exception as e:
                    messages.error(request, f"Error saving maintenance data: {e}")
            else:
                # Jika duration = 0, hapus maintenance jika ada
                Maintenance.objects.filter(bevel_machine=header).delete()

            # EDIT SHARED REASON STOP (bukan create baru)
            shared_reason_data = {
                'waiting_materials': float(waiting_materials_shared or 0),
                'meeting': float(meeting_shared or 0),
                'others': float(others_shared or 0),
                'maintenance': maintenance_obj,
                'reject': 0,
                'cutback': 0,
                'change_over': 0,
                'change_over_comment': '',
                'bjo_number': None,
            }

            # HAPUS SEMUA DUPLIKAT DULU (cleanup)
            BevelReasonStop.objects.filter(Reff=header, bjo=None).delete()
            
            # CREATE BARU (data bersih)
            BevelReasonStop.objects.create(
                Reff=header,
                bjo=None,
                **shared_reason_data
            )

            # EDIT PER BJO REASON STOPS
            for bjo_data in bjos_data:
                bjo_id = bjo_data['id']
                bjo_obj = JobHeader.objects.get(id=bjo_id)
                reason_data = bjo_reason_data.get(bjo_id, {})
                
                # HAPUS DUPLIKAT UNTUK BJO INI
                BevelReasonStop.objects.filter(Reff=header, bjo=bjo_obj).delete()
                
                # CREATE BARU (data bersih)
                BevelReasonStop.objects.create(
                    Reff=header,
                    bjo=bjo_obj,
                    bjo_number=bjo_obj.bjo,
                    reject=reason_data.get('reject', 0),
                    cutback=reason_data.get('cutback', 0),
                    change_over=reason_data.get('change_over', 0),
                    change_over_comment=reason_data.get('change_over_comment', ''),
                    waiting_materials=None,
                    meeting=None,
                    others=None,
                    maintenance=None,
                )

        # SAVE FINALIZATION RESULTS
        header.actual_output = actual_output
        header.actual_hours = actual_hours
        header.comment = comment
        header.is_posted = True
        header.save()

        messages.success(request, "Beveling record finalization successfully saved.")
        return redirect("bevel_list")

    # For GET request
    total_qty, total_hours, auto_actual_output, auto_actual_hours = calculate_totals()
    
    return render(request, "bevel/final.html", {
        "header": header,
        "total_qty": total_qty,
        "total_hours": round(total_hours, 2),
        "booked_duration": booked_duration,
        "time_difference": 0,
        "need_reason_explanation": False,
        "is_overtime": False,
        "bjos_data": bjos_data,
        "existing_shared_reason_stop": existing_shared_reason_stop,
        "existing_maintenance": existing_maintenance,
        "auto_actual_output": auto_actual_output,
        "auto_actual_hours": auto_actual_hours,
    })
    
@beveling_consumption_access_required
def bevel_consumption_list(request):
    query = request.GET.get('q', '')
    items = BevelConsumsion.objects.select_related(
        'Reff__machine', 
        'Reff__operator',
        'Reff__shift'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Bevel Header fields
            Q(Reff__machine__name__icontains=query) |
            Q(Reff__date__icontains=query) |
            Q(Reff__operator__name__icontains=query) |
            Q(Reff__shift__name__icontains=query) |
            # Bevel Consumption fields
            Q(insert_snmg__icontains=query) |
            Q(insert_dnmg__icontains=query) |
            Q(insert_bevel__icontains=query) |
            Q(others__icontains=query)
        )

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'query': query,
        'active_menu': 'bevel_consumption_list'
    }
    return render(request, 'bevel/consumption/list.html', context)


@beveling_consumption_access_required
def bevel_consumption_edit(request, pk):
    item = get_object_or_404(BevelConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data - Bevel Header tidak bisa diubah, jadi tidak perlu diupdate
            insert_snmg = request.POST.get('insert_snmg') or None
            insert_dnmg = request.POST.get('insert_dnmg') or None
            insert_bevel = request.POST.get('insert_bevel') or None
            others = request.POST.get('others') or None

            # Update BevelConsumsion
            item.insert_snmg = insert_snmg
            item.insert_dnmg = insert_dnmg
            item.insert_bevel = insert_bevel
            item.others = others
            item.save()

            messages.success(request, 'Data Bevel Consumption berhasil diperbarui.')
            return redirect('bevel_consumption_list')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
    
    context = {
        'item': item,
        'active_menu': 'bevel/consumption'
    }
    return render(request, 'bevel/consumption/edit.html', context)


@beveling_consumption_access_required
def bevel_consumption_delete(request, pk):
    item = get_object_or_404(BevelConsumsion, pk=pk)
    
    if request.method == 'POST':
        try:
            # Simpan informasi untuk pesan sebelum menghapus
            bevel_info = ""
            if item.Reff:
                machine_name = item.Reff.machine.name if item.Reff.machine else "Unknown"
                date_str = item.Reff.date.strftime('%d/%m/%Y') if item.Reff.date else "Unknown"
                bevel_info = f"{machine_name} - {date_str}"
            else:
                bevel_info = "Bevel Consumption"
            
            # Hapus data
            item.delete()
            
            messages.success(request, f'Data Bevel Consumption {bevel_info} berhasil dihapus.')
            return redirect('bevel_consumption_list')
            
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('bevel_consumption_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('bevel_consumption_list')

@beveling_ncr_access_required
def bevel_ncr_list(request):
    query = request.GET.get('q', '')
    items = BevelNcr.objects.select_related(
        'serial__Reff__machine', 
        'serial__bjo'
    ).all().order_by('-id')

    if query:
        items = items.filter(
            # Bevel Header fields
            Q(serial__Reff__machine__name__icontains=query) |
            Q(serial__Reff__date__icontains=query) |
            Q(serial__Reff__operator__name__icontains=query) |
            Q(serial__Reff__shift__name__icontains=query) |
            # Job Header fields
            Q(serial__bjo__bjo__icontains=query) |
            Q(serial__bjo__customer__icontains=query) |
            Q(serial__bjo__bt__icontains=query) |
            Q(serial__bjo__product__icontains=query) |
            # Bevel Detail fields
            Q(serial__joint_number__icontains=query) |
            # Bevel NCR fields
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
        'active_menu': 'bevel_ncr_list',
    }
    return render(request, 'bevel/ncr/list.html', context)


@beveling_ncr_access_required
def bevel_ncr_create(request):
    """
    View untuk membuat BevelNcr secara manual
    """
    if request.method == 'POST':
        try:
            with transaction.atomic():
                serial_id = request.POST.get('serial')
                reason = request.POST.get('reason', '').strip()
                disposition = request.POST.get('disposition', '').strip()
                action = request.POST.get('action', '').strip()

                # Validasi serial (BevelDetail) wajib
                if not serial_id:
                    messages.error(request, "Bevel Detail wajib dipilih.")
                    return redirect('bevel_ncr_create')

                try:
                    bevel_detail = BevelDetail.objects.get(id=serial_id)
                except BevelDetail.DoesNotExist:
                    messages.error(request, "Bevel Detail yang dipilih tidak valid.")
                    return redirect('bevel_ncr_create')

                # Cek apakah sudah ada NCR untuk bevel detail ini
                existing_ncr = BevelNcr.objects.filter(serial=bevel_detail).first()
                if existing_ncr:
                    messages.warning(
                        request, 
                        f"NCR untuk Bevel Detail (Joint: {bevel_detail.joint_number}) sudah ada. "
                        f"Silakan edit NCR yang sudah ada."
                    )
                    return redirect('bevel_ncr_edit', id=existing_ncr.id)

                # Create BevelNcr
                bevel_ncr = BevelNcr.objects.create(
                    serial=bevel_detail,
                    reason=reason if reason else None,
                    disposition=disposition if disposition else None,
                    action=action if action else None,
                )

                # Update is_ncr flag pada SerialNumber
                if bevel_detail.joint_number and bevel_detail.bjo:
                    updated_count = SerialNumber.objects.filter(
                        joint_number=bevel_detail.joint_number, 
                        bjo=bevel_detail.bjo
                    ).update(is_ncr=True)
                    
                    if updated_count > 0:
                        messages.success(
                            request, 
                            f"BevelNcr berhasil dibuat untuk Joint Number '{bevel_detail.joint_number}'. "
                            f"Status NCR pada Serial Number telah diupdate."
                        )
                    else:
                        messages.warning(
                            request,
                            f"BevelNcr berhasil dibuat untuk Joint Number '{bevel_detail.joint_number}', "
                            f"tetapi Serial Number tidak ditemukan untuk di-update."
                        )
                else:
                    messages.success(
                        request, 
                        f"BevelNcr berhasil dibuat."
                    )
                    
                return redirect('bevel_ncr_list')

        except Exception as e:
            messages.error(request, f"Terjadi kesalahan: {str(e)}")
            return redirect('bevel_ncr_create')
    
    # GET request - tampilkan form
    available_details = BevelDetail.objects.filter(
        bevelncr__isnull=True,
        is_uncompleted=False
    ).select_related(
        'Reff__machine',
        'bjo'
    ).order_by('-Reff__date', '-created_at')

    context = {
        'available_details': available_details,
        'active_menu': 'bevel_ncr_list',
    }
    return render(request, 'bevel/ncr/create.html', context)


@beveling_ncr_access_required
def bevel_ncr_edit(request, id):
    item = get_object_or_404(BevelNcr, id=id)
    
    if request.method == 'POST':
        # Update field yang bisa diedit
        item.reason = request.POST.get('reason')
        item.disposition = request.POST.get('disposition')
        item.action = request.POST.get('action')
        
        # Validasi - pastikan setidaknya ada satu field yang diisi
        if not item.reason and not item.disposition and not item.action:
            messages.error(request, "Minimal satu field (Reason, Disposition, atau Action) harus diisi.")
            return redirect('bevel_ncr_edit', id=id)
        
        item.save()
        messages.success(request, "Data Beveling NCR berhasil diperbarui.")
        return redirect('bevel_ncr_list')
    
    return render(request, 'bevel/ncr/edit.html', {
        'item': item,
        'active_menu': 'bevel_ncr_list'
    })


@beveling_ncr_access_required
def bevel_ncr_delete(request, id):
    item = get_object_or_404(BevelNcr, id=id)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Simpan informasi untuk pesan sebelum menghapus
                bevel_info = ""
                if item.serial and item.serial.Reff:
                    machine_name = item.serial.Reff.machine.name if item.serial.Reff.machine else "Unknown"
                    date_str = item.serial.Reff.date.strftime('%d/%m/%Y') if item.serial.Reff.date else "Unknown"
                    bevel_info = f"{machine_name} - {date_str}"
                else:
                    bevel_info = "Beveling NCR"
                
                # Simpan informasi joint number untuk pesan yang lebih informatif
                joint_info = f" (Joint: {item.serial.joint_number})" if item.serial and item.serial.joint_number else ""
                
                # Simpan referensi bevel_detail sebelum delete
                bevel_detail = item.serial
                joint_number = bevel_detail.joint_number if bevel_detail else None
                bjo = bevel_detail.bjo if bevel_detail else None
                
                # Hapus data NCR terlebih dahulu
                item.delete()
                
                # Reset is_ncr flag kembali ke False SETELAH delete
                # Pastikan joint_number dan bjo ada
                if joint_number and bjo:
                    # Cek apakah masih ada NCR lain untuk joint number yang sama
                    # dari proses lain (threading, phosphating, welding, dll)
                    other_ncrs_exist = False
                    
                    # Cek apakah model NCR lain ada di sistem
                    try:
                        # Cek threading NCR
                        from .models import ThreadingNcr
                        if ThreadingNcr.objects.filter(
                            serial__joint_number=joint_number,
                            serial__bjo=bjo
                        ).exists():
                            other_ncrs_exist = True
                    except (ImportError, AttributeError):
                        pass
                    
                    try:
                        # Cek phosphating NCR
                        from .models import PhosphatingNcr
                        if PhosphatingNcr.objects.filter(
                            serial__joint_number=joint_number,
                            serial__bjo=bjo
                        ).exists():
                            other_ncrs_exist = True
                    except (ImportError, AttributeError):
                        pass
                    
                    try:
                        # Cek welding NCR
                        from .models import WeldingNcr
                        if WeldingNcr.objects.filter(
                            serial__joint_number=joint_number,
                            serial__bjo=bjo
                        ).exists():
                            other_ncrs_exist = True
                    except (ImportError, AttributeError):
                        pass
                    
                    # Hanya reset is_ncr jika tidak ada NCR lain
                    if not other_ncrs_exist:
                        updated_count = SerialNumber.objects.filter(
                            joint_number=joint_number, 
                            bjo=bjo
                        ).update(is_ncr=False)
                        
                        if updated_count > 0:
                            messages.success(
                                request, 
                                f'Data Beveling NCR {bevel_info}{joint_info} berhasil dihapus. '
                                f'Status NCR pada Serial Number telah dikembalikan ke normal.'
                            )
                        else:
                            messages.warning(
                                request,
                                f'Data Beveling NCR {bevel_info}{joint_info} berhasil dihapus, '
                                f'tetapi tidak ada Serial Number yang di-update. '
                                f'Pastikan data joint number "{joint_number}" ada di Serial Number.'
                            )
                    else:
                        messages.success(
                            request,
                            f'Data Beveling NCR {bevel_info}{joint_info} berhasil dihapus. '
                            f'Status NCR pada Serial Number tetap aktif karena masih ada NCR dari proses lain.'
                        )
                else:
                    messages.success(
                        request,
                        f'Data Beveling NCR {bevel_info}{joint_info} berhasil dihapus.'
                    )
                
                return redirect('bevel_ncr_list')
                
        except Exception as e:
            messages.error(request, f'Error saat menghapus data: {str(e)}')
            return redirect('bevel_ncr_list')
    
    # Jika bukan POST, redirect ke list
    return redirect('bevel_ncr_list')

@beveling_report_access_required
def bevel_report_oee(request):
    # Get date range from request or default to current week
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not start_date or not end_date:
        # Default to current week (Sunday to Saturday)
        today = datetime.now().date()
        
        # Calculate days since last Sunday
        days_since_sunday = (today.weekday() + 1) % 7
        
        # Find the Sunday of current week
        start_date = today - timedelta(days=days_since_sunday)
        # End date is Saturday (6 days after Sunday)
        end_date = start_date + timedelta(days=6)
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        # Auto-adjust to Sunday-Saturday week if needed
        days_since_sunday = (start_date.weekday() + 1) % 7
        adjusted_start = start_date - timedelta(days=days_since_sunday)
        adjusted_end = adjusted_start + timedelta(days=6)
        
        # Use adjusted dates if the original range doesn't span exactly 7 days
        if (end_date - start_date).days != 6:
            start_date = adjusted_start
            end_date = adjusted_end
    
    # Calculate week number
    week_number = start_date.isocalendar()[1] + 1
    
    # Get all machines that are WELD type
    weld_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=weld_process)
    
    # Create date range (Sunday to Saturday)
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timedelta(days=1)
    
    # Ensure we have exactly 7 days
    assert len(date_range) == 7, "Week should contain exactly 7 days"
    
    # Get bevel headers for the date range (INCLUDE NON-POSTED RECORDS FOR DISPLAY)
    bevel_headers = BevelHeader.objects.filter(
        date__range=[start_date, end_date]
    ).select_related('machine', 'operator', 'shift', 'booked_hours')
    
    # Step 1: Calculate maximum work orders per day
    columns_per_day = {}
    
    for date in date_range:
        max_work_orders_for_date = 0
        
        for machine in machines:
            work_order_shift_combinations = []
            headers_for_machine_date = bevel_headers.filter(machine=machine, date=date)
            
            for header in headers_for_machine_date:
                details = BevelDetail.objects.filter(Reff=header).select_related('bjo')
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        work_order_shift_key = f"{detail.bjo.bjo}_{header.shift.name if header.shift else 'NO_SHIFT'}"
                        if work_order_shift_key not in work_order_shift_combinations:
                            work_order_shift_combinations.append(work_order_shift_key)
            
            max_work_orders_for_date = max(max_work_orders_for_date, len(work_order_shift_combinations))
        
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
    
    # Initialize daily summary
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
            headers_for_date = bevel_headers.filter(machine=machine, date=date)
            
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
            
            # Collect work order data
            work_order_shift_list = []
            work_order_shift_data = {}
            
            for header in headers_for_date:
                shift_name = header.shift.name if header.shift else 'NO_SHIFT'
                details = BevelDetail.objects.filter(Reff=header).select_related('bjo', 'bjo__size', 'bjo__conn')
                
                for detail in details:
                    if detail.bjo and detail.bjo.bjo:
                        work_order = detail.bjo.bjo
                        work_order_shift_key = (work_order, shift_name)
                        
                        if work_order_shift_key not in work_order_shift_list:
                            work_order_shift_list.append(work_order_shift_key)
                        
                        if work_order_shift_key not in work_order_shift_data:
                            size_display = str(detail.bjo.size) if detail.bjo.size else ''
                            if size_display:
                                size_display = size_display.replace('THREADING', '').replace('WELDING', '').replace('BEVEL', '').strip()
                            
                            work_order_shift_data[work_order_shift_key] = {
                                'header': header,
                                'shift': shift_name,
                                'details': [],
                                'bjo_obj': detail.bjo,
                                'client': detail.bjo.customer if detail.bjo.customer else '',
                                'size': size_display,
                                'connection': detail.bjo.conn.name if detail.bjo.conn else '',
                                'cycle_time': str(detail.ct) if detail.ct else '',
                                'price_book': str(detail.pb) if detail.pb else '',
                                'actual_hours': 0,
                                'output_qty': 0,
                                'non_recordable_time': 0,
                                'booked_hours_for_shift': 0,
                                'is_posted': header.is_posted,
                            }
                        work_order_shift_data[work_order_shift_key]['details'].append(detail)
            
            # Sort by shift
            def shift_sort_key(item):
                work_order, shift_name = item
                if 'SHIFT 1' in shift_name or 'Shift 1' in shift_name:
                    return (1, work_order)
                elif 'SHIFT 2' in shift_name or 'Shift 2' in shift_name:
                    return (2, work_order)
                else:
                    return (3, shift_name, work_order)
            
            work_order_shift_list.sort(key=shift_sort_key)
            
            # Calculate hours and output
            for work_order_shift_key in work_order_shift_data:
                wo_data = work_order_shift_data[work_order_shift_key]
                details = wo_data['details']
                header = wo_data['header']
                bjo_obj = wo_data['bjo_obj']
                
                total_hours = 0
                total_output = 0
                
                for detail in details:
                    if detail.start_time and detail.stop_time:
                        hours = calculate_time_duration(detail.start_time, detail.stop_time)
                        if hours is not None:
                            total_hours += hours
                    
                    # Calculate output (including uncompleted)
                    if detail.output:
                        total_output += float(detail.output)
                
                # Get reason stops
                shared_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
                bjo_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=bjo_obj).first()
                
                # Calculate non-recordable time
                total_non_recordable = 0
                if shared_reason_stops:
                    total_non_recordable = (
                        float(shared_reason_stops.waiting_materials or 0) +
                        float(shared_reason_stops.meeting or 0) +
                        float(shared_reason_stops.maintenance.duration if shared_reason_stops.maintenance else 0) +
                        float(shared_reason_stops.others or 0)
                    )
                
                if bjo_reason_stops and bjo_reason_stops.change_over:
                    total_non_recordable += float(bjo_reason_stops.change_over)
                
                wo_data['actual_hours'] = total_hours
                wo_data['output_qty'] = total_output
                wo_data['non_recordable_time'] = total_non_recordable
                wo_data['bjo_reason_stops'] = bjo_reason_stops
            
            # Distribute booked hours
            planned_hours_per_shift = {}
            work_orders_per_shift = {}
            
            for work_order_shift_key, wo_data in work_order_shift_data.items():
                shift_name = wo_data['shift']
                
                if shift_name not in planned_hours_per_shift:
                    planned_hours_per_shift[shift_name] = 0
                    work_orders_per_shift[shift_name] = []
                
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
            
            for shift_name, total_planned_hours in planned_hours_per_shift.items():
                booked_hours_for_shift = booked_hours_by_shift.get(shift_name, 0)
                work_orders_in_shift = work_orders_per_shift[shift_name]
                
                if total_planned_hours > 0:
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        proportion = wo_data['planned_hours'] / total_planned_hours
                        wo_data['booked_hours_for_shift'] = booked_hours_for_shift * proportion
                else:
                    num_work_orders = len(work_orders_in_shift)
                    allocated_hours = booked_hours_for_shift / num_work_orders if num_work_orders > 0 else 0
                    
                    for work_order_shift_key in work_orders_in_shift:
                        wo_data = work_order_shift_data[work_order_shift_key]
                        wo_data['booked_hours_for_shift'] = allocated_hours
            
            # Initialize daily data
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
                'is_posted': [True] * columns_for_this_date,
            }
            
            # Fill data for each work order
            for i, work_order_shift_key in enumerate(work_order_shift_list):
                if i < columns_for_this_date and work_order_shift_key in work_order_shift_data:
                    wo_data = work_order_shift_data[work_order_shift_key]
                    header = wo_data['header']
                    work_order, shift_name = work_order_shift_key
                    bjo_reason_stops = wo_data.get('bjo_reason_stops')
                    
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
                    daily_data['is_posted'][i] = wo_data['is_posted']
                    
                    shared_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
                    
                    if bjo_reason_stops:
                        daily_data['rejects'][i] = float(bjo_reason_stops.reject or 0)
                        daily_data['cutbacks'][i] = float(bjo_reason_stops.cutback or 0)
                        daily_data['change_over'][i] = float(bjo_reason_stops.change_over or 0)
                    else:
                        daily_data['rejects'][i] = 0
                        daily_data['cutbacks'][i] = 0
                        daily_data['change_over'][i] = 0
                    
                    work_orders_in_shift_count = len([k for k in work_order_shift_list if k[1] == shift_name])
                    
                    if shared_reason_stops and work_orders_in_shift_count > 0:
                        daily_data['wait_material'][i] = float(shared_reason_stops.waiting_materials or 0) / work_orders_in_shift_count
                        daily_data['meetings'][i] = float(shared_reason_stops.meeting or 0) / work_orders_in_shift_count
                        daily_data['breakdown'][i] = float(shared_reason_stops.maintenance.duration if shared_reason_stops.maintenance else 0) / work_orders_in_shift_count
                    else:
                        daily_data['wait_material'][i] = 0
                        daily_data['meetings'][i] = 0
                        daily_data['breakdown'][i] = 0
                    
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
                            
                            good_output = max(0, output - rejects - cutbacks)
                            
                            if booked_hours_for_this_wo > 0:
                                oee_value = ((good_output * cycle_time) / booked_hours_for_this_wo) * 100
                                oee_value = max(0, min(oee_value, 100))
                            else:
                                oee_value = 0
                            
                            daily_data['oee'][i] = round(oee_value, 2)
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
                    
                    daily_data['operating_hours'][i] = max(0, daily_data['working_hours'][i] - daily_data['non_recorded_time'][i])
                    
                    total_production = daily_data['output_qty'][i] + daily_data['rejects'][i] + daily_data['cutbacks'][i]
                    if total_production > 0:
                        daily_data['reject_rate'][i] = ((daily_data['rejects'][i] + daily_data['cutbacks'][i]) / total_production * 100)
                    else:
                        daily_data['reject_rate'][i] = 0
                    
                    if daily_data['cycle_times'][i] and booked_hours_for_this_wo > 0:
                        try:
                            cycle_time = float(daily_data['cycle_times'][i])
                            if cycle_time > 0:
                                daily_data['planned_production'][i] = booked_hours_for_this_wo / cycle_time
                        except (ValueError, TypeError):
                            daily_data['planned_production'][i] = 0
                    
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
        
        # Calculate variances
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
        
        # Calculate percentages
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
    
    # Calculate summary variance and percentage
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
    
    # Calculate summary percentages
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
        'active_menu': 'bevel_report_oee'
    }
    
    return render(request, 'bevel/report_oee.html', context)

@beveling_report_access_required
def bevel_report_oee_monthly(request):
    """
    Monthly OEE Report - Shows weekly summaries for each week in a month
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
    weld_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=weld_process)
    
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
            # Get bevel headers for this week (ONLY POSTED)
            bevel_headers = BevelHeader.objects.filter(
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
            for header in bevel_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    weekly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = BevelDetail.objects.filter(Reff=header).select_related('bjo')
                
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
                
                # Get reason stops - Bevel has both shared and per-BJO
                shared_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
                
                if shared_reason_stops:
                    weekly_summary['wait_material'] += float(shared_reason_stops.waiting_materials or 0)
                    weekly_summary['meetings'] += float(shared_reason_stops.meeting or 0)
                    weekly_summary['breakdown'] += float(shared_reason_stops.maintenance.duration if shared_reason_stops.maintenance else 0)
                    # Note: 'others' in shared is not counted separately
                
                # Get per-BJO reason stops for rejects, cutbacks, and change_over
                bjo_reason_stops = BevelReasonStop.objects.filter(Reff=header).exclude(bjo=None)
                
                for bjo_stop in bjo_reason_stops:
                    weekly_summary['rejects'] += float(bjo_stop.reject or 0)
                    weekly_summary['cutbacks'] += float(bjo_stop.cutback or 0)
                    weekly_summary['change_over'] += float(bjo_stop.change_over or 0)
            
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
        'active_menu': 'bevel_report_oee_monthly'
    }
    
    return render(request, 'bevel/report_oee_monthly.html', context)

@beveling_report_access_required
def bevel_report_oee_quarterly(request):
    """
    Quarterly OEE Report - Shows monthly summaries for each month in a quarter
    UPDATED: New OEE formula = ((Output - (Reject + Cutback)) × CT) / Booked Hours × 100%
    ONLY INCLUDES POSTED DATA
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
    weld_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=weld_process)
    
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
            # Get bevel headers for this month (ONLY POSTED)
            bevel_headers = BevelHeader.objects.filter(
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
            for header in bevel_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    monthly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = BevelDetail.objects.filter(Reff=header).select_related('bjo')
                
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
                
                # Get reason stops - Bevel has both shared and per-BJO
                shared_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
                
                if shared_reason_stops:
                    monthly_summary['wait_material'] += float(shared_reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(shared_reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(shared_reason_stops.maintenance.duration if shared_reason_stops.maintenance else 0)
                
                # Get per-BJO reason stops for rejects, cutbacks, and change_over
                bjo_reason_stops = BevelReasonStop.objects.filter(Reff=header).exclude(bjo=None)
                
                for bjo_stop in bjo_reason_stops:
                    monthly_summary['rejects'] += float(bjo_stop.reject or 0)
                    monthly_summary['cutbacks'] += float(bjo_stop.cutback or 0)
                    monthly_summary['change_over'] += float(bjo_stop.change_over or 0)
            
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
        'active_menu': 'bevel_report_oee_quarterly'
    }
    
    return render(request, 'bevel/report_oee_quarterly.html', context)

@beveling_report_access_required
def bevel_report_oee_yearly(request):
    """
    Yearly OEE Report - Shows monthly summaries for each month in a year
    UPDATED: New OEE formula = ((Output - (Reject + Cutback)) × CT) / Booked Hours × 100%
    ONLY INCLUDES POSTED DATA
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
    weld_process = Process.objects.filter(name__icontains='WELD').first()
    machines = Machine.objects.filter(process_type=weld_process)
    
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
            # Get bevel headers for this month (ONLY POSTED)
            bevel_headers = BevelHeader.objects.filter(
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
            for header in bevel_headers:
                # Booked hours
                if header.booked_hours and header.booked_hours.duration:
                    monthly_summary['booked_hours_header'] += float(header.booked_hours.duration)
                
                # Get details
                details = BevelDetail.objects.filter(Reff=header).select_related('bjo')
                
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
                
                # Get reason stops - Bevel has both shared and per-BJO
                shared_reason_stops = BevelReasonStop.objects.filter(Reff=header, bjo=None).first()
                
                if shared_reason_stops:
                    monthly_summary['wait_material'] += float(shared_reason_stops.waiting_materials or 0)
                    monthly_summary['meetings'] += float(shared_reason_stops.meeting or 0)
                    monthly_summary['breakdown'] += float(shared_reason_stops.maintenance.duration if shared_reason_stops.maintenance else 0)
                
                # Get per-BJO reason stops for rejects, cutbacks, and change_over
                bjo_reason_stops = BevelReasonStop.objects.filter(Reff=header).exclude(bjo=None)
                
                for bjo_stop in bjo_reason_stops:
                    monthly_summary['rejects'] += float(bjo_stop.reject or 0)
                    monthly_summary['cutbacks'] += float(bjo_stop.cutback or 0)
                    monthly_summary['change_over'] += float(bjo_stop.change_over or 0)
            
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
        'active_menu': 'bevel_report_oee_yearly'
    }
    
    return render(request, 'bevel/report_oee_yearly.html', context)

@beveling_access_required
def index(request):
    """
    Dashboard Bevel - Menampilkan BJO yang sudah selesai dan on progress
    """
    
    # Ambil semua BJO yang memiliki record bevel
    bevel_bjos = JobHeader.objects.filter(
        beveldetail__isnull=False
    ).distinct()
    
    # BJO yang sudah selesai di-bevel
    finished_bjos = []
    for bjo in bevel_bjos:
        # Hitung total yang sudah di-bevel
        total_beveled = BevelDetail.objects.filter(
            bjo=bjo,
            is_uncompleted=False
        ).count()
        
        if bjo.qty and total_beveled >= bjo.qty and total_beveled > 0:
            finished_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_beveled': total_beveled,
                'finish_date': BevelDetail.objects.filter(
                    bjo=bjo
                ).order_by('-created_at').first().created_at.date() if BevelDetail.objects.filter(bjo=bjo).exists() else None
            })
    
    # BJO yang sedang on progress
    progress_bjos = []
    for bjo in bevel_bjos:
        # Hitung total yang sudah di-bevel
        total_beveled = BevelDetail.objects.filter(
            bjo=bjo,
            is_uncompleted=False
        ).count()
        
        if bjo.qty and 0 < total_beveled < bjo.qty:
            remaining = bjo.qty - total_beveled
            progress_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_beveled': total_beveled,
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
        'active_menu': 'bevel',
    }
    
    return render(request, 'bevel/index.html', context)