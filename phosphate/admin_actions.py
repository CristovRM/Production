from django.contrib import admin
from django.utils import timezone
from phosphate.export import export_pipe_report_pdf, export_pipe_report_excel


@admin.action(description='Export laporan PDF harian')
def export_daily_pdf(modeladmin, request, queryset):
    today = timezone.now().date()
    filepath = f'pipe_report_{today}.pdf'
    export_pipe_report_pdf(filepath, date=today)
    modeladmin.message_user(request, f"Laporan PDF disimpan ke {filepath}")

@admin.action(description='Export laporan Excel harian')
def export_daily_excel(modeladmin, request, queryset):
    today = timezone.now().date()
    filepath = f'pipe_report_{today}.xlsx'
    export_pipe_report_excel(filepath, date=today)
    modeladmin.message_user(request, f"Laporan Excel disimpan ke {filepath}")
