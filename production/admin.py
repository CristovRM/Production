from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from .models import *
from .forms import *
from .utils import *


class CycleTimeAdmin(admin.ModelAdmin):
    form = CycleTimeForm

    class Media:
        js = ('js/cycletime_admin.js',)
        css = {
            'all': ('https://cdn.jsdelivr.net/npm/select2@4.1.0/dist/css/select2.min.css',)
        }

class JobDetailInline(admin.TabularInline):  # atau StackedInline jika mau tampilan vertikal
    model = jobDetail
    extra = 1
    fields = ['box', 'pin', 'fs', 'fc', 'finished'] 

@admin.register(JobHeader)
class JobHeaderAdmin(admin.ModelAdmin):
    list_display = ['bjo', 'customer','size','conn','product', 'bjo_for','qty', 'total_finished','remaining_qty', 'start_date','finish_date']
    search_fields = ['bjo', 'customer']
    inlines = [JobDetailInline]

class ThreadDetailInline(admin.TabularInline):  # Bisa juga StackedInline
    model = ThreadDetail
    form = ThreadDetailForm
    formset = ThreadDetailInlineFormSet
    extra = 1  # jumlah form kosong tambahan
    can_delete = True
    autocomplete_fields = ['bjo']  # jika bjo banyak data
    fields = ['start_time', 'stop_time', 'bjo','joint_number', 'pin_or_box', 'ct','pb', 'comment']

    class Media:
        css = {
            'all': ('https://cdn.jsdelivr.net/npm/select2@4.1.0/dist/css/select2.min.css',),
        }
        js = (
            'https://code.jquery.com/jquery-3.6.0.min.js',
            'https://cdn.jsdelivr.net/npm/select2@4.1.0/dist/js/select2.min.js',
        )

    def get_formset(self, request, obj=None, **kwargs):
        FormSet = super().get_formset(request, obj, **kwargs)

        class CleanedFormSet(FormSet):
            def clean(self):
                super().clean()
                print("=== DEBUG: DATA YANG DIKIRIM ===")
                for form in self.forms:
                    print(form.cleaned_data)

        return CleanedFormSet

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "joint_number":
            print("=== DEBUG: Custom queryset loaded for joint_number ===")
            kwargs["queryset"] = SerialNumber.objects.filter(
                Q(is_box_threaded=False) &
                Q(is_pin_threaded=False) 
                # Q(is_phosphated=False)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ThreadHeader)
class ThreadHeaderAdmin(admin.ModelAdmin):
    list_display = ['date', 'machine', 'operator', 'shift']
    # inlines = [ProdctionDetailInline, ConsumsionInline]
    inlines = [ThreadDetailInline]
    search_fields = ['comment']
    list_filter = ['date', 'shift', 'machine']   


@admin.register(SerialNumber)
class SerialNumberAdmin(admin.ModelAdmin):
    list_display = ['joint_number', 'bjo', 'is_box_threaded','is_pin_threaded','is_box_phosphated','is_pin_phosphated','is_bp_installed','is_pp_installed','is_used','is_ncr']
    search_fields = ['joint_number']
    change_list_template = 'admin/serialnumber_changelist.html'  # jika pakai template custom

    def has_add_permission(self, request):
        return False  # ini akan sembunyikan tombol “Add” sepenuhnya

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generate/', self.admin_site.admin_view(self.generate_serial_numbers), name='generate_serial_numbers'),
        ]
        return custom_urls + urls

    def generate_serial_numbers(self, request):
        if request.method == 'POST':
            form = SerialNumberBatchForm(request.POST)
            if form.is_valid():
                bjo = form.cleaned_data['bjo']
                start = form.cleaned_data['start_number']
                end = form.cleaned_data['end_number']

                existing = set(
                    SerialNumber.objects.filter(bjo=bjo)
                    .values_list('joint_number', flat=True)
                )

                created, duplicates = 0, []

                for number in range(start, end + 1):
                    joint = str(number).zfill(0)
                    if joint in existing:
                        duplicates.append(joint)
                        continue

                    SerialNumber.objects.create(
                        bjo=bjo,
                        joint_number=joint,
                        is_box_threaded=False,
                        is_pin_threaded=False,
                        is_box_phosphated = False,
                        is_pin_phosphated = False,
                        is_ncr=False,
                        is_used=False
                        
                    )

                    created += 1

                msg = f'{created} serial numbers berhasil dibuat untuk BJO {bjo}.'
                if duplicates:
                    msg += f' {len(duplicates)} nomor diabaikan karena sudah ada: {", ".join(duplicates[:5])}'
                    if len(duplicates) > 5:
                        msg += ', ...'
                self.message_user(request, msg)
                return redirect('..')
        else:
            form = SerialNumberBatchForm()

        return render(request, 'admin/generate_serialnumbers.html', {'form': form})


@admin.register(PinProtector)
class PinProtectorAdmin(admin.ModelAdmin):
    list_display = ['serial_number', 'bjo', 'is_used']
    search_fields = ['serial_number']
    change_list_template = 'admin/pinprotector_changelist.html'  # ganti sesuai struktur folder kamu

    def has_add_permission(self, request):
        return False  # ini akan sembunyikan tombol “Add” sepenuhnya

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generate/', self.admin_site.admin_view(self.generate_pin_serial_numbers), name='generate_pin_protectors'),
        ]
        return custom_urls + urls

    def generate_pin_serial_numbers(self, request):
        if request.method == 'POST':
            form = PinProtectorBatchForm(request.POST)
            if form.is_valid():
                bjo = form.cleaned_data['bjo']
                prefix = form.cleaned_data['prefix']
                start = form.cleaned_data['start_number']
                end = form.cleaned_data['end_number']

                created = []
                for i in range(start, end + 1):
                    serial = f"{prefix} {i:03d}"
                    PinProtector.objects.create(
                        bjo=bjo,
                        serial_number=serial,
                        is_used=False
                    )
                    created.append(serial)

                msg = f"{len(created)} PIN serial numbers berhasil dibuat untuk BJO {bjo}: {created[0]} - {created[-1]}"
                self.message_user(request, msg, level=messages.SUCCESS)
                return redirect('..')
        else:
            form = PinProtectorBatchForm()

        return render(request, 'admin/generate_pin_protectors.html', {'form': form})

    
@admin.register(BoxProtector)
class BoxProtectorAdmin(admin.ModelAdmin):
    list_display = ['serial_number', 'bjo', 'is_used']
    search_fields = ['serial_number']
    change_list_template = 'admin/boxprotector_changelist.html'  # ganti sesuai struktur folder kamu

    def has_add_permission(self, request):
        return False  # ini akan sembunyikan tombol “Add” sepenuhnya

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generate/', self.admin_site.admin_view(self.generate_box_serial_numbers), name='generate_box_protectors'),
        ]
        return custom_urls + urls

    def generate_box_serial_numbers(self, request):
        if request.method == 'POST':
            form = BoxProtectorBatchForm(request.POST)
            if form.is_valid():
                bjo = form.cleaned_data['bjo']
                prefix = form.cleaned_data['prefix']
                start = form.cleaned_data['start_number']
                end = form.cleaned_data['end_number']

                created = []
                for i in range(start, end + 1):
                    serial = f"{prefix} {i:03d}"
                    BoxProtector.objects.create(
                        bjo=bjo,
                        serial_number=serial,
                        is_used=False
                    )
                    created.append(serial)

                msg = f"{len(created)} BOX serial numbers berhasil dibuat untuk BJO {bjo}: {created[0]} - {created[-1]}"
                self.message_user(request, msg, level=messages.SUCCESS)
                return redirect('..')
        else:
            form = BoxProtectorBatchForm()

        return render(request, 'admin/generate_box_protectors.html', {'form': form})


admin.site.register(Process)
admin.site.register(Shift)
admin.site.register(Operator)
admin.site.register(Machine)
admin.site.register(PriceBook)
admin.site.register(CycleTime, CycleTimeAdmin)
admin.site.register(OdThickness)
admin.site.register(MaterialGrade)
admin.site.register(Connection)
admin.site.register(ThreadNcr)
admin.site.register(BookedHours)
admin.site.register(Maintenance)
admin.site.register(ThreadConsumsion)
admin.site.register(InfoTag)

