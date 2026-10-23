from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import *
from datetime import datetime

def update_header_metrics(header):
    if not header:
        return
    
    details = ThreadDetail.objects.filter(Reff=header)

    # ✅ FIX: Sum output dari semua detail, bukan count
    total_output = 0
    for d in details:
        if d.output:
            total_output += float(d.output)

    # Calculate total duration
    total_duration = 0
    for d in details:
        if d.start_time and d.stop_time:
            start = datetime.combine(datetime.today(), d.start_time)
            stop = datetime.combine(datetime.today(), d.stop_time)
            duration = (stop - start).total_seconds() / 3600
            total_duration += max(duration, 0)

    header.actual_output = round(total_output, 2)  # ✅ Sum output, bukan count
    header.actual_hours = round(total_duration, 2)
    header.save(update_fields=['actual_output', 'actual_hours'])
    

@receiver(post_save, sender=ThreadDetail)
def handle_thread_detail_save(sender, instance, **kwargs):
    # Pastikan header valid
    if isinstance(instance.Reff, ThreadHeader):
        update_header_metrics(instance.Reff)


@receiver(post_save, sender=ThreadDetail)
def mark_joint_used(sender, instance, **kwargs):
    joint = instance.joint_number
    pin_or_box = instance.pin_or_box
    comment = instance.comment

    if joint:
        try:
            serial = SerialNumber.objects.get(joint_number=joint)

            # Tandai threading sesuai jenis joint
            if pin_or_box == "PIN" and not serial.is_pin_threaded:
                serial.is_pin_threaded = True
            elif pin_or_box == "BOX" and not serial.is_box_threaded:
                serial.is_box_threaded = True

            # Deteksi kata 'NCR' di komentar, case-insensitive
            if comment and "ncr" in comment.lower() and not serial.is_ncr:
                serial.is_ncr = True

            serial.save(update_fields=[
                'is_pin_threaded',
                'is_box_threaded',
                'is_ncr'
            ])

        except SerialNumber.DoesNotExist:
            pass  # Joint tidak ditemukan, bisa kita log kalau perlu
        
@receiver(post_delete, sender=ThreadDetail)
def handle_thread_detail_delete(sender, instance, **kwargs):
    """Auto update ThreadHeader metrics when ThreadDetail is deleted"""
    if isinstance(instance.Reff, ThreadHeader):
        update_header_metrics(instance.Reff)

def update_weld_header_metrics(header):
    """Update actual_output and actual_hours for WeldHeader based on WeldDetail records"""
    if not header:
        return
    
    details = WeldDetail.objects.filter(Reff=header)

    # ✅ FIX: Sum output dari semua detail (uncompleted=0.5, completed=1.0)
    total_output = 0
    for d in details:
        if d.output:
            total_output += float(d.output)
    
    # Calculate total duration
    total_duration = 0
    for d in details:
        if d.start_time and d.stop_time:
            start = datetime.combine(datetime.today(), d.start_time)
            stop = datetime.combine(datetime.today(), d.stop_time)
            duration = (stop - start).total_seconds() / 3600
            total_duration += max(duration, 0)

    header.actual_output = round(total_output, 2)  # ✅ Sum output, bukan count
    header.actual_hours = round(total_duration, 2)
    header.save(update_fields=['actual_output', 'actual_hours'])
    
@receiver(post_save, sender=WeldDetail)
def handle_weld_detail_save(sender, instance, **kwargs):
    """Auto update WeldHeader metrics when WeldDetail is saved"""
    # Pastikan header valid
    if isinstance(instance.Reff, WeldHeader):
        update_weld_header_metrics(instance.Reff)
        
@receiver(post_delete, sender=WeldDetail)
def handle_weld_detail_delete(sender, instance, **kwargs):
    """Auto update WeldHeader metrics when WeldDetail is deleted"""
    if isinstance(instance.Reff, WeldHeader):
        update_weld_header_metrics(instance.Reff)
        
@receiver(post_save, sender=WeldDetail)
def mark_weld_joint_used(sender, instance, **kwargs):
    joint = instance.joint_number
    conn = instance.conn_number
    pin_or_box = instance.pin_or_box
    comment = instance.comment

    # Update SerialNumber jika menggunakan joint_number
    if joint:
        try:
            serial = SerialNumber.objects.get(joint_number=joint)

            # Deteksi kata 'NCR' di komentar, case-insensitive
            if comment and "ncr" in comment.lower() and not serial.is_ncr:
                serial.is_ncr = True
                serial.save(update_fields=['is_ncr'])

        except SerialNumber.DoesNotExist:
            pass  # Joint tidak ditemukan, bisa kita log kalau perlu