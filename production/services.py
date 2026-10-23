from decimal import Decimal
from django.db.models import Sum, Q

def calculate_custom_oee(header_instance):
    """
    Calculate OEE using standard formula: Availability × Performance × Quality
    OEE = (Available Time / Planned Time) × (Actual Output / Standard Output) × (Good Output / Total Output)
    Works for both ThreadHeader and WeldHeader
    """
    from .models import CycleTime, ThreadDetail, WeldDetail, TreadReasonStop, WeldReasonStop
    
    # Determine if this is ThreadHeader or WeldHeader
    is_thread = header_instance.__class__.__name__ == 'ThreadHeader'
    
    # Get related data
    if is_thread:
        job_detail = header_instance.threaddetail_set.first()
    else:
        job_detail = header_instance.welddetail_set.first()
    
    job = job_detail.bjo if job_detail else None
    
    if not job:
        return {
            'oee_percentage': Decimal('0'),
            'availability': Decimal('0'),
            'performance': Decimal('0'),
            'quality': Decimal('0'),
            'message': 'No job data found'
        }

    # Get cycle time standard
    cycle_time_obj = CycleTime.objects.filter(
        process_type=job.process_type,
        od_thickness=job.size,
        ct_for=job.ct_reference
    ).first()

    # Get basic data
    actual_output = header_instance.actual_output or Decimal('0')
    actual_hours = header_instance.actual_hours or Decimal('0')
    booked_hours = header_instance.booked_hours.duration if header_instance.booked_hours else Decimal('0')
    standard_cycle_time = cycle_time_obj.hours if cycle_time_obj and cycle_time_obj.hours else Decimal('0')

    # Validation
    if booked_hours == 0:
        return {
            'oee_percentage': Decimal('0'),
            'availability': Decimal('0'),
            'performance': Decimal('0'),
            'quality': Decimal('0'),
            'message': 'No booked hours data'
        }

    if standard_cycle_time == 0:
        return {
            'oee_percentage': Decimal('0'),
            'availability': Decimal('0'),
            'performance': Decimal('0'),
            'quality': Decimal('0'),
            'message': 'No standard cycle time data'
        }

    # Calculate AVAILABILITY
    availability = calculate_availability(header_instance, booked_hours, is_thread)
    
    # Calculate PERFORMANCE
    performance = calculate_performance(
        actual_output, 
        actual_hours or booked_hours, 
        standard_cycle_time
    )
    
    # Calculate QUALITY
    quality = calculate_quality(header_instance, actual_output, is_thread)
    
    # Calculate final OEE
    oee_decimal = availability * performance * quality
    oee_percentage = round(oee_decimal * 100, 2)
    
    return {
        'oee_percentage': oee_percentage,
        'availability': round(availability * 100, 2),
        'performance': round(performance * 100, 2),
        'quality': round(quality * 100, 2),
        'message': 'Success'
    }


def calculate_availability(header_instance, planned_time, is_thread=True):
    """
    Availability = (Planned Time - Downtime) / Planned Time
    """
    from .models import TreadReasonStop, WeldReasonStop
    
    # Get the correct ReasonStop model based on header type
    if is_thread:
        reason_stops = TreadReasonStop.objects.filter(
            Reff=header_instance
        ).aggregate(
            total_waiting_materials=Sum('waiting_materials'),
            total_meeting=Sum('meeting'),
            total_others=Sum('others')
        )
    else:
        reason_stops = WeldReasonStop.objects.filter(
            Reff=header_instance
        ).aggregate(
            total_waiting_materials=Sum('waiting_materials'),
            total_meeting=Sum('meeting'),
            total_others=Sum('others')
        )
    
    # Calculate total downtime
    waiting_materials = reason_stops['total_waiting_materials'] or Decimal('0')
    meeting = reason_stops['total_meeting'] or Decimal('0')
    others = reason_stops['total_others'] or Decimal('0')
    
    # Add maintenance downtime if exists
    maintenance_downtime = Decimal('0')
    if is_thread:
        maintenance_records = TreadReasonStop.objects.filter(
            Reff=header_instance,
            maintenance__isnull=False
        ).select_related('maintenance')
    else:
        maintenance_records = WeldReasonStop.objects.filter(
            Reff=header_instance,
            maintenance__isnull=False
        ).select_related('maintenance')
    
    for record in maintenance_records:
        if record.maintenance and hasattr(record.maintenance, 'duration'):
            maintenance_downtime += record.maintenance.duration or Decimal('0')
    
    total_downtime = waiting_materials + meeting + others + maintenance_downtime
    available_time = planned_time - total_downtime
    
    if planned_time == 0:
        return Decimal('0')
    
    # Ensure availability doesn't exceed 100%
    availability = min(max(available_time / planned_time, Decimal('0')), Decimal('1'))
    return availability


def calculate_performance(actual_output, operating_time, standard_cycle_time):
    """
    Performance = (Actual Output × Standard Cycle Time) / Operating Time
    or
    Performance = Actual Output / (Operating Time / Standard Cycle Time)
    """
    if operating_time == 0 or standard_cycle_time == 0:
        return Decimal('0')
    
    # Calculate standard output that should be produced
    standard_output = operating_time / standard_cycle_time
    
    if standard_output == 0:
        return Decimal('0')
    
    performance = actual_output / standard_output
    
    # Performance shouldn't exceed 100% in normal cases, but allow it for analysis
    return max(performance, Decimal('0'))


def calculate_quality(header_instance, actual_output, is_thread=True):
    """
    Quality = (Good Output) / (Total Output)
    Good Output = Actual Output - Rejects - Cutbacks
    """
    from .models import TreadReasonStop, WeldReasonStop
    
    if actual_output == 0:
        return Decimal('0')
    
    # Get reject and cutback data from the correct model
    if is_thread:
        reason_stop_data = TreadReasonStop.objects.filter(
            Reff=header_instance
        ).aggregate(
            total_reject=Sum('reject'),
            total_cutback=Sum('cutback')
        )
    else:
        reason_stop_data = WeldReasonStop.objects.filter(
            Reff=header_instance
        ).aggregate(
            total_reject=Sum('reject'),
            total_cutback=Sum('cutback')
        )
    
    reject = reason_stop_data['total_reject'] or Decimal('0')
    cutback = reason_stop_data['total_cutback'] or Decimal('0')
    
    # Calculate good output
    total_defects = reject + cutback
    good_output = actual_output - total_defects
    
    # Ensure good output is not negative
    good_output = max(good_output, Decimal('0'))
    
    quality = good_output / actual_output
    
    # Quality should be between 0 and 1
    return min(max(quality, Decimal('0')), Decimal('1'))


def get_oee_analysis(header_instance):
    """
    Get detailed OEE analysis with actionable insights
    """
    oee_data = calculate_custom_oee(header_instance)
    
    if oee_data['oee_percentage'] == 0:
        return oee_data
    
    # Add analysis insights
    availability = oee_data['availability']
    performance = oee_data['performance'] 
    quality = oee_data['quality']
    
    insights = []
    recommendations = []
    
    # Availability analysis
    if availability < 85:
        insights.append(f"Availability rendah ({availability}%) - ada masalah downtime")
        recommendations.append("Kurangi waktu waiting materials, meeting, dan maintenance")
    
    # Performance analysis  
    if performance < 85:
        insights.append(f"Performance rendah ({performance}%) - produksi di bawah standar")
        recommendations.append("Periksa cycle time aktual vs standar, tingkatkan efisiensi operator")
    
    # Quality analysis
    if quality < 95:
        insights.append(f"Quality rendah ({quality}%) - banyak reject/cutback")
        recommendations.append("Fokus pada quality control dan pengurangan defect")
    
    oee_data.update({
        'insights': insights,
        'recommendations': recommendations,
        'grade': get_oee_grade(oee_data['oee_percentage'])
    })
    
    return oee_data


def get_oee_grade(oee_percentage):
    """
    Classify OEE performance grade
    """
    if oee_percentage >= 85:
        return "World Class"
    elif oee_percentage >= 65:
        return "Good"
    elif oee_percentage >= 40:
        return "Fair"
    else:
        return "Poor"


# Backward compatibility - simple function that returns just percentage
def calculate_simple_oee(header_instance):
    """
    Simple function that returns OEE percentage only (for backward compatibility)
    """
    result = calculate_custom_oee(header_instance)
    return result['oee_percentage']