from django.utils import timezone
from django.db.models import Count, Sum, Q
from phosphate.models import PipePhosphate, PinProtectorPhosphate, BoxProtectorPhosphate

def get_daily_pipe_report(date=None, shift=None):
    date = date or timezone.now().date()
    qs = PipePhosphate.objects.filter(date__date=date)
    if shift:
        qs = qs.filter(shift=shift)
    return qs.select_related(
        'bjo', 'joint_number', 'box_protector', 'pin_protector', 'operator', 'shift'
    )

def get_installed_protectors(shift=None):
    pin = PinProtectorPhosphate.objects.filter(is_installed=True)
    box = BoxProtectorPhosphate.objects.filter(is_installed=True)
    if shift:
        pin = pin.filter(shift=shift)
        box = box.filter(shift=shift)
    return pin.select_related('operator', 'shift'), box.select_related('operator', 'shift')

def get_incomplete_pipes(shift=None):
    qs = PipePhosphate.objects.filter(is_completed=False)
    if shift:
        qs = qs.filter(shift=shift)
    return qs.select_related('bjo', 'joint_number', 'operator', 'shift')

def get_bjo_shift_summary():
    return PipePhosphate.objects.values('bjo__bjo', 'shift__name').annotate(
        total_joints=Count('id'),
        total_tally=Sum('tally'),
        completed=Count('id', filter=Q(is_completed=True))
    ).order_by('bjo__bjo', 'shift__name')
