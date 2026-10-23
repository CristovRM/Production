from .models import *
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from datetime import datetime, date
from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from production.models import *
from functools import wraps
from django.utils import timezone

# ============================================
# CUSTOM DECORATOR FOR ROLE-BASED ACCESS
# ============================================

def cutting_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        allowed_roles = ['operator', 'supervisor', 'admin', 'management', 'leadman']
        
        if request.user.role not in allowed_roles:
            messages.error(request, "You don't have permission to access Cutting Module. Only Operator, Supervisor, Admin, and Management can access this page.")
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================
# CUTTING VIEWS - RESTRICTED ACCESS
# ============================================

@cutting_access_required
def cutting_summary(request):
    """
    View untuk menampilkan summary/list data Cutting dengan jumlah detail
    """
    # Ambil parameter filter dengan validasi
    query = request.GET.get('q', '').strip()
    filter_bjo = request.GET.get('bjo', '').strip()
    filter_station = request.GET.get('station', '').strip()
    filter_shift = request.GET.get('shift', '').strip()
    filter_year = request.GET.get('year', '').strip()
    filter_month = request.GET.get('month', '').strip()
    filter_date = request.GET.get('date', '').strip()

    # Query dasar dengan annotate untuk hitung detail
    all_cut = cut_header.objects.select_related('bjo_protector', 'operator', 'shift').annotate(
        total_cuts=Count('cut_detail', distinct=True)
    ).all()

    # Filter pencarian (hanya jika query tidak kosong)
    if query:
        all_cut = all_cut.filter(
            Q(bjo_protector__bjo__icontains=query) |
            Q(operator__name__icontains=query)
        )

    # Filter BJO (hanya jika tidak kosong)
    if filter_bjo:
        try:
            all_cut = all_cut.filter(bjo_protector__bjo=filter_bjo)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter Station (hanya jika tidak kosong)
    if filter_station:
        all_cut = all_cut.filter(station=filter_station)

    # Filter Shift (hanya jika tidak kosong)
    if filter_shift:
        try:
            all_cut = all_cut.filter(shift__id=filter_shift)
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tahun
    if filter_year:
        try:
            all_cut = all_cut.filter(created_at__year=int(filter_year))
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan bulan (membutuhkan tahun juga)
    if filter_month and filter_year:
        try:
            all_cut = all_cut.filter(
                created_at__year=int(filter_year),
                created_at__month=int(filter_month)
            )
        except (ValueError, TypeError):
            pass  # Skip jika ada error

    # Filter berdasarkan tanggal spesifik
    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
            all_cut = all_cut.filter(created_at__date=date_obj)
        except ValueError:
            pass  # Ignore invalid date format

    all_cut = all_cut.order_by('-id')

    # Pagination
    paginator = Paginator(all_cut, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opsi untuk dropdown dengan error handling
    try:
        bjo_options = cut_header.objects.filter(
            bjo_protector__isnull=False
        ).values_list('bjo_protector__bjo', flat=True).distinct().order_by('bjo_protector__bjo')
    except Exception:
        bjo_options = []
    
    try:
        station_options = cut_header.objects.filter(
            station__isnull=False
        ).exclude(
            station=''
        ).values_list('station', flat=True).distinct().order_by('station')
    except Exception:
        station_options = []
    
    try:
        # Ambil shift options dengan ID dan nama
        shift_options = cut_header.objects.filter(
            shift__isnull=False
        ).values_list('shift__id', 'shift__name').distinct().order_by('shift__id')
    except Exception:
        shift_options = []

    # Opsi tahun berdasarkan data yang ada
    try:
        year_options = cut_header.objects.dates('created_at', 'year').values_list('created_at__year', flat=True).distinct()
    except Exception:
        year_options = []

    # Opsi bulan (1-12)
    month_options = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    context = {
        'all_cut': page_obj,
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
        'active_menu': 'cutting_summary',
    }

    return render(request, 'summary.html', context)


@cutting_access_required
def cutting_header(request):
    """
    View untuk membuat header cutting baru
    """
    if request.method == 'POST':
        bjo_id = request.POST.get('bjo')
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')
        
        # Validasi input
        if not all([bjo_id, station, shift_id, operator_id]):
            messages.error(request, 'Semua field harus diisi!')
            return redirect('cutting_header')
        
        try:
            # Ambil objek dari database
            bjo = JobHeader.objects.get(id=bjo_id)
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)
            
            # Buat header cutting baru
            new_cut = cut_header.objects.create(
                bjo_protector=bjo,
                station=station,
                shift=shift,
                operator=operator
            )
            
            messages.success(request, f'Header cutting untuk BJO {bjo.bjo} berhasil dibuat!')
            # Redirect ke halaman detail untuk input cutting details
            return redirect('cutting_detail', header_id=new_cut.id)
            
        except JobHeader.DoesNotExist:
            messages.error(request, 'BJO tidak ditemukan!')
            return redirect('cutting_header')
        except Shift.DoesNotExist:
            messages.error(request, 'Shift tidak ditemukan!')
            return redirect('cutting_header')
        except Operator.DoesNotExist:
            messages.error(request, 'Operator tidak ditemukan!')
            return redirect('cutting_header')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')
            return redirect('cutting_header')
    
    # GET request - tampilkan form
    try:
        # Ambil BJO yang bjo_for adalah PIPE dan belum selesai (is_finish=False)
        job_list = JobHeader.objects.filter(
            is_finish=False,
            bjo_for="PIPE"
        ).order_by('bjo')
        
    except Exception as e:
        print(f"Error loading job list: {e}")
        job_list = []
    
    try:
        operator_list = Operator.objects.all().order_by('name')
    except Exception:
        operator_list = []
    
    try:
        shift_list = Shift.objects.all().order_by('id')
    except Exception:
        shift_list = []
    
    # Station list - sesuaikan dengan kebutuhan
    station_list = [
        'CUTTING AREA',
    ]
    
    context = {
        'job_list': job_list,
        'operator_list': operator_list,
        'shift_list': shift_list,
        'station_list': station_list,
        'active_menu': 'cutting_header',
    }
    
    return render(request, 'header.html', context)


@cutting_access_required
def cutting_delete(request, header_id):
    """
    View untuk menghapus data cutting header beserta detailnya
    """
    if request.method == 'POST':
        try:
            # Ambil data header
            header = cut_header.objects.get(id=header_id)
            bjo_name = header.bjo_protector.bjo
            
            # Hapus header (detail akan terhapus otomatis karena CASCADE)
            header.delete()
            
            messages.success(request, f'Data cutting untuk BJO {bjo_name} berhasil dihapus!')
            
        except cut_header.DoesNotExist:
            messages.error(request, 'Data tidak ditemukan!')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')
    
    return redirect('cutting_summary')


@cutting_access_required
def cutting_detail(request, header_id):
    """
    View untuk input detail cutting record
    """
    header = get_object_or_404(cut_header, id=header_id)

    # Ambil SEMUA protector dari database (tidak tergantung BJO header)
    pin_protector_list = PinProtector.objects.all().order_by('serial_number')
    box_protector_list = BoxProtector.objects.all().order_by('serial_number')
    
    # Gabungkan kedua list untuk ditampilkan di template
    protector_list = []
    
    # Tambahkan PIN PROTECTOR dengan label
    for pin in pin_protector_list:
        protector_list.append({
            'id': f'PIN_{pin.id}',
            'serial_number': pin.serial_number,
            'type': 'PIN PROTECTOR',
            'bjo': pin.bjo.bjo if pin.bjo else '-',
            'actual_id': pin.id
        })
    
    # Tambahkan BOX PROTECTOR dengan label
    for box in box_protector_list:
        protector_list.append({
            'id': f'BOX_{box.id}',
            'serial_number': box.serial_number,
            'type': 'BOX PROTECTOR',
            'bjo': box.bjo.bjo if box.bjo else '-',
            'actual_id': box.id
        })

    if request.method == 'POST':
        joint_number = request.POST.get('joint_number', '').strip()
        protector_id = request.POST.get('protector')
        
        # Validasi input
        if not joint_number:
            messages.error(request, 'Joint Number harus diisi!')
            return redirect('cutting_detail', header_id=header.id)
            
        if not protector_id:
            messages.error(request, 'Protector Number harus dipilih!')
            return redirect('cutting_detail', header_id=header.id)
        
        try:
            # Parse protector_id untuk mendapatkan tipe dan actual_id
            # Format: PIN_{id} atau BOX_{id}
            protector_type, actual_id = protector_id.split('_')
            
            # Ambil protector berdasarkan tipe
            if protector_type == "PIN":
                protector = get_object_or_404(PinProtector, id=actual_id)
                protector_number_str = protector.serial_number
                
            elif protector_type == "BOX":
                protector = get_object_or_404(BoxProtector, id=actual_id)
                protector_number_str = protector.serial_number
            else:
                messages.error(request, 'Tipe Protector tidak valid!')
                return redirect('cutting_detail', header_id=header.id)

            # Cek duplikasi joint number dalam cutting record yang sama
            existing_joint = cut_detail.objects.filter(
                reff=header,
                joint_number=joint_number
            ).exists()
            
            if existing_joint:
                messages.warning(request, f'Joint Number {joint_number} sudah ada dalam record ini!')
                return redirect('cutting_detail', header_id=header.id)

            # Simpan ke cut_detail
            cut_detail.objects.create(
                reff=header,
                joint_number=joint_number,
                protector_number=protector_number_str
            )
            messages.success(request, f'Data berhasil disimpan! Joint: {joint_number}, Protector: {protector_number_str}')
            return redirect('cutting_detail', header_id=header.id)
            
        except ValueError:
            messages.error(request, 'Format Protector ID tidak valid!')
            return redirect('cutting_detail', header_id=header.id)
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')
            return redirect('cutting_detail', header_id=header.id)

    # Ambil existing details untuk ditampilkan
    existing_details = cut_detail.objects.filter(reff=header).order_by('-created_at')

    context = {
        'active_menu': 'cutting_record',
        'header': header,
        'protector_list': protector_list,
        'existing_details': existing_details,
    }
    
    return render(request, 'detail.html', context)


@cutting_access_required
def cutting_edit(request, header_id):
    """
    View untuk edit header cutting (station, shift, operator)
    """
    header = get_object_or_404(cut_header, id=header_id)
    
    if request.method == 'POST':
        station = request.POST.get('station')
        shift_id = request.POST.get('shift')
        operator_id = request.POST.get('operator')
        
        # Validasi input
        if not all([station, shift_id, operator_id]):
            messages.error(request, 'Semua field harus diisi!')
            return redirect('cutting_edit', header_id=header.id)
        
        try:
            # Update header
            shift = Shift.objects.get(id=shift_id)
            operator = Operator.objects.get(id=operator_id)
            
            header.station = station
            header.shift = shift
            header.operator = operator
            header.save()
            
            messages.success(request, 'Data header berhasil diupdate!')
            return redirect('cutting_summary')
            
        except Shift.DoesNotExist:
            messages.error(request, 'Shift tidak ditemukan!')
        except Operator.DoesNotExist:
            messages.error(request, 'Operator tidak ditemukan!')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')
        
        return redirect('cutting_edit', header_id=header.id)
    
    # GET request - tampilkan form edit
    try:
        operator_list = Operator.objects.all().order_by('name')
    except Exception:
        operator_list = []
    
    try:
        shift_list = Shift.objects.all().order_by('id')
    except Exception:
        shift_list = []
    
    station_list = ['CUTTING AREA']
    
    context = {
        'header': header,
        'operator_list': operator_list,
        'shift_list': shift_list,
        'station_list': station_list,
        'active_menu': 'cutting_summary',
    }
    
    return render(request, 'edit.html', context)


@cutting_access_required
def cutting_report(request, header_id):
    """
    View untuk cetak laporan cutting record
    """
    selected_headers = get_object_or_404(
        cut_header.objects.select_related('bjo_protector', 'operator', 'shift')
        .prefetch_related('cut_detail_set'), 
        id=header_id
    )
    
    context = {
        'active_menu': 'cutting_report',
        'selected_headers': selected_headers
    }
    
    return render(request, 'report.html', context)


def index(request):
    """
    Dashboard Cutting - Menampilkan BJO Pipe yang sudah selesai dan on progress
    """
    
    # Ambil semua BJO untuk PIPE saja
    pipe_bjos = JobHeader.objects.filter(bjo_for='PIPE')
    
    # BJO yang sudah selesai di-cut (memiliki cut_header dan semua qty sudah di-cut)
    finished_bjos = []
    for bjo in pipe_bjos:
        # Hitung total yang sudah di-cut
        total_cut = cut_detail.objects.filter(
            reff__bjo_protector=bjo
        ).count()
        
        if bjo.qty and total_cut >= bjo.qty and total_cut > 0:
            finished_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_cut': total_cut,
                'finish_date': cut_header.objects.filter(
                    bjo_protector=bjo
                ).order_by('-created_at').first().created_at.date() if cut_header.objects.filter(bjo_protector=bjo).exists() else None
            })
    
    # BJO yang sedang on progress (sudah mulai di-cut tapi belum selesai)
    progress_bjos = []
    for bjo in pipe_bjos:
        # Hitung total yang sudah di-cut
        total_cut = cut_detail.objects.filter(
            reff__bjo_protector=bjo
        ).count()
        
        if bjo.qty and 0 < total_cut < bjo.qty:
            remaining = bjo.qty - total_cut
            progress_bjos.append({
                'bjo': bjo.bjo,
                'customer': bjo.customer,
                'size': bjo.size,
                'qty': bjo.qty,
                'total_cut': total_cut,
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
    }
    
    return render(request, 'cutting/index.html', context)