from django.contrib import admin
from django.forms.models import BaseInlineFormSet
from .models import *
from .forms import *

# Inline untuk BoxDetail
class BoxDetailInline(admin.TabularInline):
    model = BoxDetail
    extra = 1

@admin.register(BoxHeader)
class BoxHeaderAdmin(admin.ModelAdmin):
    form = BoxHeaderForm
    inlines = [BoxDetailInline]
    exclude = ['is_phosphated', 'is_installed']
    list_display = ['created_at', 'station', 'shift', 'operator']


# Inline untuk PinDetail
class PinDetailInline(admin.TabularInline):
    model = PinDetail
    extra = 1

@admin.register(PinHeader)
class PinHeaderAdmin(admin.ModelAdmin):
    form = PinHeaderForm
    inlines = [PinDetailInline]
    exclude = ['is_phosphated', 'is_installed']
    list_display = ['created_at', 'station', 'shift', 'operator']


# PipeDetailInlineFormSet yang ditingkatkan tanpa readonly_fields
class PipeDetailInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for form in self.forms:
            instance = form.instance
            if instance.pk:  # Jika instance sudah ada (edit)
                # Hilangkan pembatasan readonly_fields
                pass
            else:
                # Form baru, lakukan pemfilteran queryset
                form.fields['joint_number'].queryset = SerialNumber.objects.filter(is_used=False)
                form.fields['pin_protector'].queryset = PinDetail.objects.filter(is_installed=False)
                form.fields['box_protector'].queryset = BoxDetail.objects.filter(is_installed=False)


# Inline untuk PipeDetail
class PipeDetailInline(admin.TabularInline):
    model = PipeDetail
    extra = 1
    formset = PipeDetailInlineFormSet

    fields = [
        'joint_number',
        'pin_protector',
        'pin_installed_by',
        'box_protector',
        'box_installed_by',
        'tally',
        'is_box_completed',
        'is_pin_completed',
        'is_completed',
    ]
    readonly_fields = ['created_at', 'modified_at']  # Menampilkan readonly fields di tampilan admin

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)

        class FilteredFormSet(formset):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for form in self.forms:
                    instance = form.instance

                    # Form lama (edit), tidak perlu memfilter lagi
                    if instance.pk:
                        continue
                    
                    # Form baru (belum ada instance), lakukan filter queryset
                    form.fields['joint_number'].queryset = SerialNumber.objects.filter(is_used=False)
                    form.fields['pin_protector'].queryset = PinDetail.objects.filter(is_installed=False)
                    form.fields['box_protector'].queryset = BoxDetail.objects.filter(is_installed=False)

        return FilteredFormSet


@admin.register(PipeHeader)
class PipeHeaderAdmin(admin.ModelAdmin):
    form = PipeHeaderForm
    inlines = [PipeDetailInline]
    exclude = ['is_box_completed', 'is_pin_completed', 'is_completed']
    list_display = ['created_at', 'station', 'shift', 'operator']


# Custom FormSet untuk menyembunyikan field tertentu
class PipePhosphateDetailInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for form in self.forms:
            for field_name in ['box_phosphated', 'pin_phosphated', 'created_at', 'modified_at']:
                form.fields.pop(field_name, None)

# Inline admin untuk PipePhosphateDetail
class PipePhosphateDetailInline(admin.TabularInline):
    model = PipePhosphateDetail
    extra = 1
    form = PipePhosphateDetailForm

# Admin utama untuk PipePhosphateHeader
class PipePhosphateHeaderAdmin(admin.ModelAdmin):
    inlines = [PipePhosphateDetailInline]
    form = PipePhosphateHeaderForm

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj
        return super().get_form(request, obj, **kwargs)

admin.site.register(PipePhosphateHeader, PipePhosphateHeaderAdmin)
