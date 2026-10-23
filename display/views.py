from django.shortcuts import render, redirect, get_object_or_404
from datetime import date, timedelta
from django.db.models import Q
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from .models import *
from production.models import *
from django.views.generic.edit import CreateView
from .models import Produksi
from .forms import ProduksiForm
from functools import wraps
from django.http import JsonResponse

# ============================================
# CUSTOM DECORATOR FOR ROLE-BASED ACCESS
# ============================================

def display_access_required(view_func):
    """
    Decorator untuk membatasi akses hanya untuk:
    - Admin
    - Management
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        allowed_roles = ['admin', 'management', 'leadman', 'supervisor']
        
        if request.user.role not in allowed_roles:
            messages.error(request, "You don't have permission to access Information Display Module. Only Admin and Management can access this page.")
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================
# DISPLAY VIEWS - RESTRICTED ACCESS
# ============================================

class ProduksiCreateView(CreateView):
    """
    Class-based view untuk create Produksi
    Catatan: Untuk CBV, gunakan UserPassesTestMixin atau LoginRequiredMixin
    """
    model = Produksi
    form_class = ProduksiForm
    template_name = 'produksi_form.html'
    success_url = '/produksi/'
    
    # Tambahkan method untuk check permission
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.role not in ['admin', 'management']:
            messages.error(request, "You don't have permission to access Information Display Module. Only Admin and Management can access this page.")
            return redirect('dashboard')
        
        return super().dispatch(request, *args, **kwargs)


@display_access_required
def produksi_create(request):
    """
    Function-based view untuk create Produksi
    """
    if request.method == 'POST':
        form = ProduksiForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('produksi_tambah')
    else:
        form = ProduksiForm()
    
    return render(request, 'produksi_form.html', {'form': form})


@display_access_required
def index(request):
    """
    Dashboard menampilkan data kemarin
    """
    yesterday = date.today() - timedelta(days=1)
    print(Data.objects.filter(date=yesterday).count())
    queryset = Data.objects.filter(date=yesterday)

    def translate_shift_name(shift_nama):
        shift_map = {
            'SHIFT 1': 'DAY SHIFT',
            'SHIFT 2': 'NIGHT SHIFT'
        }
        return shift_map.get(shift_nama, shift_nama)

    def extract_chart_data(queryset, proses_nama, shift_nama):
        filtered = queryset.filter(
            process__name=proses_nama, 
            shift__name=shift_nama).order_by('machine__name')
        
        label = f'{proses_nama} - {translate_shift_name(shift_nama)}'
        return {
            'label': label,
            'oee': [float(d.oee or 0) for d in filtered],
            'reject': [float(d.reject or 0) for d in filtered],
            'not_run': [float(d.non_recordable or 0) for d in filtered],
            'machines': [d.machine.name for d in filtered]
        }

    chart_data = {
        'threading_day': extract_chart_data(queryset, 'THREADING', 'SHIFT 1'),
        'welding_day': extract_chart_data(queryset, 'WELDING', 'SHIFT 1'),
        'threading_night': extract_chart_data(queryset, 'THREADING', 'SHIFT 2'),
        'welding_night': extract_chart_data(queryset, 'WELDING', 'SHIFT 2'),
    }

    konteks = {
        'chart_data': chart_data,
        'date_date': yesterday
    }

    return render(request, 'info.html', konteks)


@display_access_required
def grafikdata_list(request):
    """
    List data grafik dengan filter dan pagination
    """
    query = request.GET.get('q', '')
    process_filter = request.GET.get('process', '')
    
    items = Data.objects.all().order_by('-created_at')

    if query:
        items = items.filter(
            Q(date__icontains=query) |
            Q(process__name__icontains=query) |
            Q(machine__name__icontains=query) |
            Q(shift__name__icontains=query) |
            Q(oee__icontains=query)
        )
    
    if process_filter:
        items = items.filter(process__id=process_filter)

    paginator = Paginator(items, 20)
    page_number = request.GET.get('page')
    items = paginator.get_page(page_number)
    processes = Process.objects.all().order_by('name')

    context = {
        'items': items,
        'query': query,
        'process_filter': process_filter,
        'processes': processes,
        'active_menu': 'grafikdata_list',
    }
    return render(request, 'grafikdata/list.html', context)


@display_access_required
def grafikdata_add(request):
    """
    Tambah data grafik baru
    """
    # Ambil pilihan untuk foreign keys
    processes = Process.objects.all()
    machines = Machine.objects.all()
    shifts = Shift.objects.all()
    
    # Set tanggal default ke kemarin
    yesterday = date.today() - timedelta(days=1)
    default_date = yesterday.strftime('%Y-%m-%d')

    if request.method == 'POST':
        try:
            date_input = request.POST.get('date', '').strip()
            process_id = request.POST.get('process', '').strip()
            machine_id = request.POST.get('machine', '').strip()
            shift_id = request.POST.get('shift', '').strip()
            booking_hours = request.POST.get('booking_hours', '').strip()
            output = request.POST.get('output', '').strip()
            ct = request.POST.get('ct', '').strip()
            reject = request.POST.get('reject', '').strip()
            non_recordable = request.POST.get('non_recordable', '').strip()

            # Validasi wajib
            if not date_input:
                messages.error(request, "Tanggal wajib diisi.")
                return render(request, 'grafikdata/add.html', {
                    'processes': processes,
                    'machines': machines,
                    'shifts': shifts,
                    'active_menu': 'grafikdata',
                    'date': default_date,
                    'process_id': process_id,
                    'machine_id': machine_id,
                    'shift_id': shift_id,
                    'booking_hours': booking_hours,
                    'output': output,
                    'ct': ct,
                    'reject': reject,
                    'non_recordable': non_recordable
                })

            # Konversi ke objek atau None
            process = Process.objects.get(id=process_id) if process_id else None
            machine = Machine.objects.get(id=machine_id) if machine_id else None
            shift = Shift.objects.get(id=shift_id) if shift_id else None

            # Konversi decimal fields
            booking_hours_val = float(booking_hours) if booking_hours else None
            output_val = float(output) if output else None
            ct_val = float(ct) if ct else None
            reject_val = float(reject) if reject else None
            non_recordable_val = float(non_recordable) if non_recordable else None

            Data.objects.create(
                date=date_input,
                process=process,
                machine=machine,
                shift=shift,
                booking_hours=booking_hours_val,
                output=output_val,
                ct=ct_val,
                reject=reject_val,
                non_recordable=non_recordable_val
            )
            
            messages.success(request, "Data berhasil ditambahkan.")
            return redirect('grafikdata_list')

        except ValueError as e:
            messages.error(request, f'Format angka tidak valid: {str(e)}')
            return render(request, 'grafikdata/add.html', {
                'processes': processes,
                'machines': machines,
                'shifts': shifts,
                'active_menu': 'grafikdata_list',
                'date': default_date
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menambah Data: {str(e)}')
            return render(request, 'grafikdata/add.html', {
                'processes': processes,
                'machines': machines,
                'shifts': shifts,
                'active_menu': 'grafikdata_list',
                'date': default_date
            })

    return render(request, 'grafikdata/add.html', {
        'processes': processes,
        'machines': machines,
        'shifts': shifts,
        'active_menu': 'grafikdata_list',
        'date': default_date
    })


@display_access_required
def grafikdata_edit(request, pk):
    """
    Edit data grafik
    """
    item = get_object_or_404(Data, pk=pk)
    processes = Process.objects.all()
    machines = Machine.objects.all()
    shifts = Shift.objects.all()

    if request.method == 'POST':
        try:
            date = request.POST.get('date', '').strip()
            process_id = request.POST.get('process', '').strip()
            machine_id = request.POST.get('machine', '').strip()
            shift_id = request.POST.get('shift', '').strip()
            booking_hours = request.POST.get('booking_hours', '').strip()
            output = request.POST.get('output', '').strip()
            ct = request.POST.get('ct', '').strip()
            reject = request.POST.get('reject', '').strip()
            non_recordable = request.POST.get('non_recordable', '').strip()

            # Validasi wajib diisi
            if not date:
                messages.error(request, "Tanggal wajib diisi.")
                return render(request, 'grafikdata/edit.html', {
                    'item': item,
                    'processes': processes,
                    'machines': machines,
                    'shifts': shifts,
                    'active_menu': 'grafikdata_list',
                })

            # Konversi ke objek atau None
            process = Process.objects.get(id=process_id) if process_id else None
            machine = Machine.objects.get(id=machine_id) if machine_id else None
            shift = Shift.objects.get(id=shift_id) if shift_id else None

            # Konversi decimal fields
            booking_hours_val = float(booking_hours) if booking_hours else None
            output_val = float(output) if output else None
            ct_val = float(ct) if ct else None
            reject_val = float(reject) if reject else None
            non_recordable_val = float(non_recordable) if non_recordable else None

            # Update data
            item.date = date
            item.process = process
            item.machine = machine
            item.shift = shift
            item.booking_hours = booking_hours_val
            item.output = output_val
            item.ct = ct_val
            item.reject = reject_val
            item.non_recordable = non_recordable_val
            item.save()

            messages.success(request, "Data berhasil diperbarui.")
            return redirect('grafikdata_list')

        except ValueError as e:
            messages.error(request, f'Format angka tidak valid: {str(e)}')
            return render(request, 'grafikdata/edit.html', {
                'item': item,
                'processes': processes,
                'machines': machines,
                'shifts': shifts,
                'active_menu': 'grafikdata_list',
            })
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat mengupdate Data: {str(e)}')
            return render(request, 'grafikdata/edit.html', {
                'item': item,
                'processes': processes,
                'machines': machines,
                'shifts': shifts,
                'active_menu': 'grafikdata_list',
            })

    return render(request, 'grafikdata/edit.html', {
        'item': item,
        'processes': processes,
        'machines': machines,
        'shifts': shifts,
        'active_menu': 'grafikdata_list',
    })


@display_access_required
def grafikdata_delete(request, id):
    """
    Hapus data grafik
    """
    if request.method == 'POST':
        try:
            data_item = get_object_or_404(Data, id=id)
            
            # Simpan info untuk pesan
            data_info = f"{data_item.date} - {data_item.process or 'N/A'}"
            
            data_item.delete()
            
            messages.success(request, f'Data "{data_info}" berhasil dihapus.')
            
            # Redirect kembali ke list dengan filter yang sama
            redirect_url = reverse('grafikdata_list')
            query_params = []
            
            if request.GET.get('q'):
                query_params.append(f"q={request.GET.get('q')}")
            if request.GET.get('page'):
                query_params.append(f"page={request.GET.get('page')}")
                
            if query_params:
                redirect_url += '?' + '&'.join(query_params)
                
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat menghapus Data: {str(e)}')
            return redirect('grafikdata_list')
    
    return redirect('grafikdata_list')


@display_access_required
def info2(request):
    """
    Dashboard khusus weekend yang menampilkan data Sabtu dan Minggu
    """
    today = date.today()
    
    # Cari tanggal Sabtu dan Minggu terdekat (kemarin atau hari ini)
    if today.weekday() == 5:  # Hari ini Sabtu
        saturday = today
        sunday = today + timedelta(days=1)
    elif today.weekday() == 6:  # Hari ini Minggu
        saturday = today - timedelta(days=1)
        sunday = today
    else:  # Hari kerja, ambil weekend sebelumnya
        days_since_saturday = (today.weekday() + 2) % 7
        saturday = today - timedelta(days=days_since_saturday)
        sunday = saturday + timedelta(days=1)
    
    # Ambil data untuk kedua hari
    saturday_data = Data.objects.filter(date=saturday)
    sunday_data = Data.objects.filter(date=sunday)
    
    print(f"Saturday ({saturday}): {saturday_data.count()} records")
    print(f"Sunday ({sunday}): {sunday_data.count()} records")

    def translate_shift_name(shift_nama):
        shift_map = {
            'SHIFT 1': 'DAY SHIFT',
            'SHIFT 2': 'NIGHT SHIFT'
        }
        return shift_map.get(shift_nama, shift_nama)

    def extract_chart_data(queryset, proses_nama, shift_nama, day_label):
        filtered = queryset.filter(
            process__name=proses_nama, 
            shift__name=shift_nama).order_by('machine__name')
        
        label = f'{proses_nama} - {translate_shift_name(shift_nama)} ({day_label})'
        return {
            'label': label,
            'oee': [float(d.oee or 0) for d in filtered],
            'reject': [float(d.reject or 0) for d in filtered],
            'not_run': [float(d.non_recordable or 0) for d in filtered],
            'machines': [d.machine.name if d.machine else 'Unknown' for d in filtered]
        }

    # Data untuk Sabtu
    saturday_charts = {
        'threading_day': extract_chart_data(saturday_data, 'THREADING', 'SHIFT 1', 'Saturday'),
        'welding_day': extract_chart_data(saturday_data, 'WELDING', 'SHIFT 1', 'Saturday'),
        'threading_night': extract_chart_data(saturday_data, 'THREADING', 'SHIFT 2', 'Saturday'),
        'welding_night': extract_chart_data(saturday_data, 'WELDING', 'SHIFT 2', 'Saturday'),
    }
    
    # Data untuk Minggu
    sunday_charts = {
        'threading_day': extract_chart_data(sunday_data, 'THREADING', 'SHIFT 1', 'Sunday'),
        'welding_day': extract_chart_data(sunday_data, 'WELDING', 'SHIFT 1', 'Sunday'),
        'threading_night': extract_chart_data(sunday_data, 'THREADING', 'SHIFT 2', 'Sunday'),
        'welding_night': extract_chart_data(sunday_data, 'WELDING', 'SHIFT 2', 'Sunday'),
    }

    konteks = {
        'saturday_data': saturday_charts,
        'sunday_data': sunday_charts,
        'saturday_date': saturday,
        'sunday_date': sunday,
        'has_saturday_data': saturday_data.exists(),
        'has_sunday_data': sunday_data.exists()
    }

    return render(request, 'info2.html', konteks)


@display_access_required
def oee_dashboard(request):
    """
    Dashboard yang menampilkan:
    - Senin: Data Sabtu & Minggu
    - Selasa-Minggu: Data hari kemarin
    
    Mengambil data OEE dari THREADING dan WELDING dengan rumus yang sama dengan report
    """
    from datetime import date, timedelta, datetime
    from django.db.models import Q
    
    today = date.today()
    today_weekday = today.weekday()  # Monday=0, Sunday=6
    
    # Logika penentuan tanggal yang ditampilkan
    if today_weekday == 0:  # Hari ini SENIN
        # Tampilkan data Sabtu & Minggu kemarin
        saturday = today - timedelta(days=2)  # Sabtu kemarin
        sunday = today - timedelta(days=1)    # Minggu kemarin
        show_two_days = True
    else:  # Selasa sampai Minggu
        # Tampilkan hanya data KEMARIN
        yesterday = today - timedelta(days=1)
        saturday = yesterday
        sunday = None
        show_two_days = False
    
    # GET ALL MACHINES (THREADING)
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    all_threading_machines = []
    if threading_process:
        all_threading_machines = list(
            Machine.objects.filter(process_type=threading_process)
            .order_by('name')
            .values_list('name', flat=True)
        )
    
    # GET ALL MACHINES (WELDING)
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    all_welding_machines = []
    if welding_process:
        all_welding_machines = list(
            Machine.objects.filter(process_type=welding_process)
            .order_by('name')
            .values_list('name', flat=True)
        )
    
    # ========== FUNGSI UNTUK THREADING ==========
    def get_threading_day_oee_data(target_date):
        """Mengambil data OEE Threading dengan rumus dari thread_report_oee"""
        if target_date is None:
            return None
            
        threading_process = Process.objects.filter(name__icontains='THREAD').first()
        if not threading_process:
            return None
            
        machines = Machine.objects.filter(process_type=threading_process)
        
        headers = ThreadHeader.objects.filter(
            date=target_date,
            is_posted=True
        ).select_related('machine', 'shift', 'booked_hours')
        
        if not headers.exists():
            return None
        
        day_shift_data = {}
        night_shift_data = {}
        
        for header in headers:
            machine = header.machine
            shift_name = header.shift.name if header.shift else ''
            
            is_day_shift = 'SHIFT 1' in shift_name or 'DAY' in shift_name.upper()
            is_night_shift = 'SHIFT 2' in shift_name or 'NIGHT' in shift_name.upper()
            
            if not is_day_shift and not is_night_shift:
                continue
            
            booked_hours = float(header.booked_hours.duration) if header.booked_hours and header.booked_hours.duration else 0
            
            if booked_hours == 0:
                continue
            
            details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
            
            total_output = 0
            cycle_time = 0
            
            for detail in details:
                if detail.output:
                    total_output += float(detail.output)
                if detail.ct and cycle_time == 0:
                    cycle_time = float(detail.ct)
            
            reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
            total_rejects = 0
            total_cutbacks = 0
            if reason_stops:
                total_rejects = float(reason_stops.reject or 0)
                total_cutbacks = float(reason_stops.cutback or 0)
            
            total_downtime = 0
            if reason_stops:
                total_downtime = (
                    float(reason_stops.waiting_materials or 0) +
                    float(reason_stops.meeting or 0) +
                    float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) +
                    float(reason_stops.change_over or 0) +
                    float(reason_stops.others or 0)
                )
            
            # RUMUS OEE DARI thread_report_oee:
            # OEE = ((Good Output × CT) / Booked Hours) × 100%
            # Good Output = Output - Reject - Cutback
            oee_value = 0
            
            if booked_hours > 0 and cycle_time > 0 and total_output > 0:
                try:
                    good_output = total_output - total_rejects - total_cutbacks
                    good_output = max(0, good_output)
                    
                    oee_value = ((good_output * cycle_time) / booked_hours) * 100
                    oee_value = max(0, min(oee_value, 100))
                    
                except (ZeroDivisionError, ValueError, TypeError):
                    oee_value = 0
            
            machine_name = machine.name if machine else 'Unknown'
            target_shift_data = day_shift_data if is_day_shift else night_shift_data
            
            if machine_name not in target_shift_data:
                target_shift_data[machine_name] = {
                    'oee_values': [],
                    'reject': 0,
                    'non_recordable': 0,
                    'count': 0
                }
            
            if oee_value > 0:
                target_shift_data[machine_name]['oee_values'].append(oee_value)
            target_shift_data[machine_name]['reject'] += total_rejects
            target_shift_data[machine_name]['non_recordable'] += total_downtime
            target_shift_data[machine_name]['count'] += 1
        
        return {
            'day_shift': day_shift_data,
            'night_shift': night_shift_data
        }
    
    # ========== FUNGSI UNTUK WELDING ==========
    def get_welding_day_oee_data(target_date):
        """Mengambil data OEE Welding dengan rumus dari weld_report_oee"""
        if target_date is None:
            return None
            
        welding_process = Process.objects.filter(name__icontains='WELD').first()
        if not welding_process:
            return None
            
        machines = Machine.objects.filter(process_type=welding_process)
        
        headers = WeldHeader.objects.filter(
            date=target_date,
            is_posted=True
        ).select_related('machine', 'shift', 'booked_hours')
        
        if not headers.exists():
            return None
        
        day_shift_data = {}
        night_shift_data = {}
        
        for header in headers:
            machine = header.machine
            shift_name = header.shift.name if header.shift else ''
            
            is_day_shift = 'SHIFT 1' in shift_name or 'DAY' in shift_name.upper()
            is_night_shift = 'SHIFT 2' in shift_name or 'NIGHT' in shift_name.upper()
            
            if not is_day_shift and not is_night_shift:
                continue
            
            booked_hours = float(header.booked_hours.duration) if header.booked_hours and header.booked_hours.duration else 0
            
            if booked_hours == 0:
                continue
            
            details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
            
            total_output = 0
            cycle_time = 0
            
            for detail in details:
                if detail.output:
                    total_output += float(detail.output)
                if detail.ct and cycle_time == 0:
                    cycle_time = float(detail.ct)
            
            reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
            total_rejects = 0
            total_cutbacks = 0
            if reason_stops:
                total_rejects = float(reason_stops.reject or 0)
                total_cutbacks = float(reason_stops.cutback or 0)
            
            total_downtime = 0
            if reason_stops:
                total_downtime = (
                    float(reason_stops.waiting_materials or 0) +
                    float(reason_stops.meeting or 0) +
                    float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) +
                    float(reason_stops.others or 0)
                )
            
            # RUMUS OEE DARI weld_report_oee (SAMA DENGAN THREADING):
            # OEE = ((Good Output × CT) / Booked Hours) × 100%
            # Good Output = Output - Reject - Cutback
            oee_value = 0
            
            if booked_hours > 0 and cycle_time > 0 and total_output > 0:
                try:
                    good_output = total_output - total_rejects - total_cutbacks
                    good_output = max(0, good_output)
                    
                    oee_value = ((good_output * cycle_time) / booked_hours) * 100
                    oee_value = max(0, min(oee_value, 100))
                    
                except (ZeroDivisionError, ValueError, TypeError):
                    oee_value = 0
            
            machine_name = machine.name if machine else 'Unknown'
            target_shift_data = day_shift_data if is_day_shift else night_shift_data
            
            if machine_name not in target_shift_data:
                target_shift_data[machine_name] = {
                    'oee_values': [],
                    'reject': 0,
                    'non_recordable': 0,
                    'count': 0
                }
            
            if oee_value > 0:
                target_shift_data[machine_name]['oee_values'].append(oee_value)
            target_shift_data[machine_name]['reject'] += total_rejects
            target_shift_data[machine_name]['non_recordable'] += total_downtime
            target_shift_data[machine_name]['count'] += 1
        
        return {
            'day_shift': day_shift_data,
            'night_shift': night_shift_data
        }
    
    # Format chart data helper
    def format_chart_data(machine_dict, all_machines_list, process_name, shift_label, day_label):
        """Format chart data ensuring ALL machines appear on X-axis"""
        machines = all_machines_list
        oee_list = []
        reject_list = []
        not_run_list = []
        
        for machine in machines:
            if machine in machine_dict:
                data = machine_dict[machine]
                avg_oee = round(sum(data['oee_values']) / len(data['oee_values']), 2) if data['oee_values'] else 0
                total_reject = round(data['reject'], 2)
                total_non_recordable = round(data['non_recordable'], 2)
                
                oee_list.append(avg_oee)
                reject_list.append(total_reject)
                not_run_list.append(total_non_recordable)
            else:
                oee_list.append(0)
                reject_list.append(0)
                not_run_list.append(0)
        
        return {
            'label': f'{process_name.upper()} - {shift_label} ({day_label})',
            'machines': machines,
            'oee': oee_list,
            'reject': reject_list,
            'not_run': not_run_list
        }
    
    # Get data for the date(s) - THREADING
    saturday_threading = get_threading_day_oee_data(saturday)
    sunday_threading = get_threading_day_oee_data(sunday) if show_two_days else None
    
    # Get data for the date(s) - WELDING
    saturday_welding = get_welding_day_oee_data(saturday)
    sunday_welding = get_welding_day_oee_data(sunday) if show_two_days else None
    
    # Determine labels based on day
    if show_two_days:
        first_label = f"Saturday {saturday.strftime('%d %b')}"
        second_label = f"Sunday {sunday.strftime('%d %b')}"
    else:
        first_label = f"Yesterday {saturday.strftime('%A, %d %b')}"
        second_label = ""
    
    # Format for charts - Saturday/Yesterday
    saturday_charts = {
        'threading_day': format_chart_data(
            saturday_threading['day_shift'] if saturday_threading else {},
            all_threading_machines,
            'Threading',
            'DAY SHIFT',
            first_label
        ),
        'threading_night': format_chart_data(
            saturday_threading['night_shift'] if saturday_threading else {},
            all_threading_machines,
            'Threading',
            'NIGHT SHIFT',
            first_label
        ),
        'welding_day': format_chart_data(
            saturday_welding['day_shift'] if saturday_welding else {},
            all_welding_machines,
            'Welding',
            'DAY SHIFT',
            first_label
        ),
        'welding_night': format_chart_data(
            saturday_welding['night_shift'] if saturday_welding else {},
            all_welding_machines,
            'Welding',
            'NIGHT SHIFT',
            first_label
        ),
    }
    
    # Format for Sunday charts (only on Monday)
    sunday_charts = {
        'threading_day': format_chart_data(
            sunday_threading['day_shift'] if sunday_threading else {},
            all_threading_machines,
            'Threading',
            'DAY SHIFT',
            second_label
        ),
        'threading_night': format_chart_data(
            sunday_threading['night_shift'] if sunday_threading else {},
            all_threading_machines,
            'Threading',
            'NIGHT SHIFT',
            second_label
        ),
        'welding_day': format_chart_data(
            sunday_welding['day_shift'] if sunday_welding else {},
            all_welding_machines,
            'Welding',
            'DAY SHIFT',
            second_label
        ),
        'welding_night': format_chart_data(
            sunday_welding['night_shift'] if sunday_welding else {},
            all_welding_machines,
            'Welding',
            'NIGHT SHIFT',
            second_label
        ),
    }
    
    context = {
        'saturday_data': saturday_charts,
        'sunday_data': sunday_charts,
        'saturday_date': saturday,
        'sunday_date': sunday,
        'has_saturday_threading': saturday_threading is not None,
        'has_saturday_welding': saturday_welding is not None,
        'has_sunday_threading': sunday_threading is not None,
        'has_sunday_welding': sunday_welding is not None,
        'show_two_days': show_two_days,
        'today': today,
        'is_monday': today_weekday == 0,
        'first_label': first_label,
        'second_label': second_label,
    }
    
    return render(request, 'oee_dashboard.html', context)

@display_access_required
def oee_dashboard_data(request):
    """
    API endpoint untuk mengambil data OEE secara AJAX (auto-refresh)
    Mengembalikan data Threading dan Welding dalam format JSON
    """
    from datetime import date, timedelta
    
    today = date.today()
    today_weekday = today.weekday()
    
    if today_weekday == 0:
        saturday = today - timedelta(days=2)
        sunday = today - timedelta(days=1)
        show_two_days = True
    else:
        yesterday = today - timedelta(days=1)
        saturday = yesterday
        sunday = None
        show_two_days = False
    
    # GET ALL MACHINES
    threading_process = Process.objects.filter(name__icontains='THREAD').first()
    all_threading_machines = []
    if threading_process:
        all_threading_machines = list(
            Machine.objects.filter(process_type=threading_process)
            .order_by('name')
            .values_list('name', flat=True)
        )
    
    welding_process = Process.objects.filter(name__icontains='WELD').first()
    all_welding_machines = []
    if welding_process:
        all_welding_machines = list(
            Machine.objects.filter(process_type=welding_process)
            .order_by('name')
            .values_list('name', flat=True)
        )
    
    # FUNGSI THREADING (sama seperti di atas)
    def get_threading_day_oee_data(target_date):
        if target_date is None:
            return None
        threading_process = Process.objects.filter(name__icontains='THREAD').first()
        if not threading_process:
            return None
        machines = Machine.objects.filter(process_type=threading_process)
        headers = ThreadHeader.objects.filter(date=target_date, is_posted=True).select_related('machine', 'shift', 'booked_hours')
        if not headers.exists():
            return None
        
        day_shift_data = {}
        night_shift_data = {}
        
        for header in headers:
            machine = header.machine
            shift_name = header.shift.name if header.shift else ''
            is_day_shift = 'SHIFT 1' in shift_name or 'DAY' in shift_name.upper()
            is_night_shift = 'SHIFT 2' in shift_name or 'NIGHT' in shift_name.upper()
            if not is_day_shift and not is_night_shift:
                continue
            
            booked_hours = float(header.booked_hours.duration) if header.booked_hours and header.booked_hours.duration else 0
            if booked_hours == 0:
                continue
            
            details = ThreadDetail.objects.filter(Reff=header).select_related('bjo')
            total_output = 0
            cycle_time = 0
            for detail in details:
                if detail.output:
                    total_output += float(detail.output)
                if detail.ct and cycle_time == 0:
                    cycle_time = float(detail.ct)
            
            reason_stops = TreadReasonStop.objects.filter(Reff=header).first()
            total_rejects = 0
            total_cutbacks = 0
            if reason_stops:
                total_rejects = float(reason_stops.reject or 0)
                total_cutbacks = float(reason_stops.cutback or 0)
            
            total_downtime = 0
            if reason_stops:
                total_downtime = (
                    float(reason_stops.waiting_materials or 0) +
                    float(reason_stops.meeting or 0) +
                    float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) +
                    float(reason_stops.change_over or 0) +
                    float(reason_stops.others or 0)
                )
            
            oee_value = 0
            if booked_hours > 0 and cycle_time > 0 and total_output > 0:
                try:
                    good_output = max(0, total_output - total_rejects - total_cutbacks)
                    oee_value = max(0, min(((good_output * cycle_time) / booked_hours) * 100, 100))
                except (ZeroDivisionError, ValueError, TypeError):
                    oee_value = 0
            
            machine_name = machine.name if machine else 'Unknown'
            target_shift_data = day_shift_data if is_day_shift else night_shift_data
            
            if machine_name not in target_shift_data:
                target_shift_data[machine_name] = {'oee_values': [], 'reject': 0, 'non_recordable': 0, 'count': 0}
            
            if oee_value > 0:
                target_shift_data[machine_name]['oee_values'].append(oee_value)
            target_shift_data[machine_name]['reject'] += total_rejects
            target_shift_data[machine_name]['non_recordable'] += total_downtime
            target_shift_data[machine_name]['count'] += 1
        
        return {'day_shift': day_shift_data, 'night_shift': night_shift_data}
    
    # FUNGSI WELDING (sama seperti di atas)
    def get_welding_day_oee_data(target_date):
        if target_date is None:
            return None
        welding_process = Process.objects.filter(name__icontains='WELD').first()
        if not welding_process:
            return None
        machines = Machine.objects.filter(process_type=welding_process)
        headers = WeldHeader.objects.filter(date=target_date, is_posted=True).select_related('machine', 'shift', 'booked_hours')
        if not headers.exists():
            return None
        
        day_shift_data = {}
        night_shift_data = {}
        
        for header in headers:
            machine = header.machine
            shift_name = header.shift.name if header.shift else ''
            is_day_shift = 'SHIFT 1' in shift_name or 'DAY' in shift_name.upper()
            is_night_shift = 'SHIFT 2' in shift_name or 'NIGHT' in shift_name.upper()
            if not is_day_shift and not is_night_shift:
                continue
            
            booked_hours = float(header.booked_hours.duration) if header.booked_hours and header.booked_hours.duration else 0
            if booked_hours == 0:
                continue
            
            details = WeldDetail.objects.filter(Reff=header).select_related('bjo')
            total_output = 0
            cycle_time = 0
            for detail in details:
                if detail.output:
                    total_output += float(detail.output)
                if detail.ct and cycle_time == 0:
                    cycle_time = float(detail.ct)
            
            reason_stops = WeldReasonStop.objects.filter(Reff=header).first()
            total_rejects = 0
            total_cutbacks = 0
            if reason_stops:
                total_rejects = float(reason_stops.reject or 0)
                total_cutbacks = float(reason_stops.cutback or 0)
            
            total_downtime = 0
            if reason_stops:
                total_downtime = (
                    float(reason_stops.waiting_materials or 0) +
                    float(reason_stops.meeting or 0) +
                    float(reason_stops.maintenance.duration if reason_stops.maintenance else 0) +
                    float(reason_stops.others or 0)
                )
            
            oee_value = 0
            if booked_hours > 0 and cycle_time > 0 and total_output > 0:
                try:
                    good_output = max(0, total_output - total_rejects - total_cutbacks)
                    oee_value = max(0, min(((good_output * cycle_time) / booked_hours) * 100, 100))
                except (ZeroDivisionError, ValueError, TypeError):
                    oee_value = 0
            
            machine_name = machine.name if machine else 'Unknown'
            target_shift_data = day_shift_data if is_day_shift else night_shift_data
            
            if machine_name not in target_shift_data:
                target_shift_data[machine_name] = {'oee_values': [], 'reject': 0, 'non_recordable': 0, 'count': 0}
            
            if oee_value > 0:
                target_shift_data[machine_name]['oee_values'].append(oee_value)
            target_shift_data[machine_name]['reject'] += total_rejects
            target_shift_data[machine_name]['non_recordable'] += total_downtime
            target_shift_data[machine_name]['count'] += 1
        
        return {'day_shift': day_shift_data, 'night_shift': night_shift_data}
    
    def format_chart_data(machine_dict, all_machines_list, process_name, shift_label, day_label):
        machines = all_machines_list
        oee_list = []
        reject_list = []
        not_run_list = []
        
        for machine in machines:
            if machine in machine_dict:
                data = machine_dict[machine]
                avg_oee = round(sum(data['oee_values']) / len(data['oee_values']), 2) if data['oee_values'] else 0
                total_reject = round(data['reject'], 2)
                total_non_recordable = round(data['non_recordable'], 2)
                oee_list.append(avg_oee)
                reject_list.append(total_reject)
                not_run_list.append(total_non_recordable)
            else:
                oee_list.append(0)
                reject_list.append(0)
                not_run_list.append(0)
        
        return {
            'label': f'{process_name.upper()} - {shift_label} ({day_label})',
            'machines': machines,
            'oee': oee_list,
            'reject': reject_list,
            'not_run': not_run_list
        }
    
    # Get data
    saturday_threading = get_threading_day_oee_data(saturday)
    sunday_threading = get_threading_day_oee_data(sunday) if show_two_days else None
    saturday_welding = get_welding_day_oee_data(saturday)
    sunday_welding = get_welding_day_oee_data(sunday) if show_two_days else None
    
    # Labels
    if show_two_days:
        first_label = f"Saturday {saturday.strftime('%d %b')}"
        second_label = f"Sunday {sunday.strftime('%d %b')}"
    else:
        first_label = f"Yesterday {saturday.strftime('%A, %d %b')}"
        second_label = ""
    
    # Format data
    saturday_charts = {
        'threading_day': format_chart_data(saturday_threading['day_shift'] if saturday_threading else {}, all_threading_machines, 'Threading', 'DAY SHIFT', first_label),
        'threading_night': format_chart_data(saturday_threading['night_shift'] if saturday_threading else {}, all_threading_machines, 'Threading', 'NIGHT SHIFT', first_label),
        'welding_day': format_chart_data(saturday_welding['day_shift'] if saturday_welding else {}, all_welding_machines, 'Welding', 'DAY SHIFT', first_label),
        'welding_night': format_chart_data(saturday_welding['night_shift'] if saturday_welding else {}, all_welding_machines, 'Welding', 'NIGHT SHIFT', first_label),
    }
    
    sunday_charts = {
        'threading_day': format_chart_data(sunday_threading['day_shift'] if sunday_threading else {}, all_threading_machines, 'Threading', 'DAY SHIFT', second_label),
        'threading_night': format_chart_data(sunday_threading['night_shift'] if sunday_threading else {}, all_threading_machines, 'Threading', 'NIGHT SHIFT', second_label),
        'welding_day': format_chart_data(sunday_welding['day_shift'] if sunday_welding else {}, all_welding_machines, 'Welding', 'DAY SHIFT', second_label),
        'welding_night': format_chart_data(sunday_welding['night_shift'] if sunday_welding else {}, all_welding_machines, 'Welding', 'NIGHT SHIFT', second_label),
    }
    
    return JsonResponse({
        'saturday_data': saturday_charts,
        'sunday_data': sunday_charts,
        'has_saturday_threading': saturday_threading is not None,
        'has_saturday_welding': saturday_welding is not None,
        'has_sunday_threading': sunday_threading is not None,
        'has_sunday_welding': sunday_welding is not None,
        'show_two_days': show_two_days,
        'first_label': first_label,
        'second_label': second_label,
    })