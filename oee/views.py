from django.shortcuts import render
from production.models import ThreadHeader, ThreadDetail,TreadReasonStop, WeldHeader, WeldDetail, WeldReasonStop
from django.db.models import Sum, F
from datetime import datetime, timedelta
from django.utils import timezone
import decimal

def oee_threadi(request):
    pass

def oee_welding(request):
    pass


def calculate_oee_stats(process_type, start_date, end_date, machine_id=None, bjo_number=None):
    """
    Menghitung OEE untuk rentang waktu tertentu.
    process_type: 'THREAD' atau 'WELD'
    """
    
    # 1. Tentukan Model berdasarkan proses
    if process_type.upper() == 'THREAD':
        from .models import ThreadHeader as Header, ThreadDetail as Detail, TreadReasonStop as ReasonStop
    else:
        from .models import WeldHeader as Header, WeldDetail as Detail, WeldReasonStop as ReasonStop

    # 2. Filter Header
    headers = Header.objects.filter(date__range=[start_date, end_date])
    if machine_id:
        headers = headers.filter(machine_id=machine_id)
    
    header_ids = headers.values_list('id', flat=True)

    # 3. Ambil Agregasi Data
    # Total Jam Terjadwal (Booked Hours)
    total_booked = headers.aggregate(total=Sum('booked_hours__duration'))['total'] or 0
    
    # Total Output & Total Target Time (Output * CT)
    # Kita asumsikan CT di Detail adalah waktu ideal per unit dalam jam
    details = Detail.objects.filter(Reff_id__in=header_ids)
    if bjo_number:
        details = details.filter(bjo_number=bjo_number)
        
    actual_output = details.aggregate(total=Sum('output'))['total'] or 0
    
    # Ideal Time = Sum of (Output * CT)
    ideal_run_time = details.aggregate(
        total=Sum(F('output') * F('ct'), output_field=models.DecimalField())
    )['total'] or 0

    # 4. Ambil Downtime & Rejects (ReasonStop)
    reasons = ReasonStop.objects.filter(Reff_id__in=header_ids)
    if bjo_number:
        reasons = reasons.filter(bjo_number=bjo_number)

    # Downtime = Maintenance + Waiting + Meeting + ChangeOver + Others
    # Kita asumsikan field di ReasonStop adalah dalam satuan JAM
    downtime_data = reasons.aggregate(
        maint=Sum('maintenance__duration'),
        waiting=Sum('waiting_materials'),
        mtg=Sum('meeting'),
        co=Sum(F('change_over') if process_type == 'THREAD' else 0),
        oth=Sum('others')
    )
    
    total_downtime = sum(filter(None, [
        downtime_data['maint'], 
        downtime_data['waiting'], 
        downtime_data['mtg'], 
        downtime_data['co'], 
        downtime_data['oth']
    ]))

    total_reject = reasons.aggregate(total=Sum('reject'))['total'] or 0

    # 5. Kalkulasi OEE
    # Availability = (Operating Time) / Planned Production Time
    operating_time = max(0, float(total_booked) - float(total_downtime))
    availability = (operating_time / float(total_booked)) if total_booked > 0 else 0

    # Performance = (Ideal Time) / Operating Time
    performance = (float(ideal_run_time) / operating_time) if operating_time > 0 else 0
    
    # Quality = (Good Units) / Total Units
    quality = ((float(actual_output) - float(total_reject)) / float(actual_output)) if actual_output > 0 else 0

    oee_score = (availability * performance * quality) * 100

    return {
        "oee_score": round(oee_score, 2),
        "availability": round(availability * 100, 2),
        "performance": round(performance * 100, 2),
        "quality": round(quality * 100, 2),
        "details": {
            "total_output": actual_output,
            "total_reject": total_reject,
            "total_downtime_hours": total_downtime,
            "operating_time": operating_time
        }
    }

def get_oee_report(process_type, period_type='daily', machine_id=None):
    """
    Helper untuk mendapatkan range tanggal berdasarkan periode
    period_type: 'daily', 'weekly', 'monthly', '4month', 'yearly'
    """
    today = timezone.now().date()
    
    if period_type == 'daily':
        start_date = today
    elif period_type == 'weekly':
        start_date = today - timedelta(days=7)
    elif period_type == 'monthly':
        start_date = today - timedelta(days=30)
    elif period_type == '4month':
        start_date = today - timedelta(days=120)
    elif period_type == 'yearly':
        start_date = today - timedelta(days=365)
    else:
        start_date = today

    return calculate_oee_stats(process_type, start_date, today, machine_id=machine_id)