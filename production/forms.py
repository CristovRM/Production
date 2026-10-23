from django import forms
from django_select2.forms import Select2Widget
from .models import *
from django.forms.models import BaseInlineFormSet
from django.forms.widgets import Widget
from django.utils.safestring import mark_safe
from django.db.models import Q

class CycleTimeForm(forms.ModelForm):
    class Meta:
        model = CycleTime
        fields = '__all__'
        widgets = {
            'process_type': Select2Widget,
            'machine_type': Select2Widget,
        }

    def clean(self):
        cleaned_data = super().clean()
        process_type = cleaned_data.get('process_type')
        machine = cleaned_data.get('machine_type')

        if machine and machine.process_type != process_type:
            raise forms.ValidationError("Mesin yang dipilih tidak sesuai dengan jenis proses.")
        
class SerialNumberBatchForm(forms.Form):
    bjo = forms.ModelChoiceField(queryset=JobHeader.objects.filter(bjo_for='PIPE',is_finish=False), label="Pilih BJO")
    start_number = forms.IntegerField(min_value=1, label="Mulai dari")
    end_number = forms.IntegerField(min_value=1, label="Sampai dengan")

    def clean(self):
        cleaned_data = super().clean()
        bjo = cleaned_data.get('bjo')
        start = cleaned_data.get('start_number')
        end = cleaned_data.get('end_number')

        if bjo and start and end:
            count_existing = PinProtector.objects.filter(bjo=bjo).count()
            total_requested = end - start + 1

            if total_requested <= 0:
                raise forms.ValidationError("Nomor akhir harus lebih besar atau sama dengan nomor awal.")

            if count_existing + total_requested > bjo.qty:
                raise forms.ValidationError(
                    f"Jumlah PIN yang akan dibuat ({total_requested}) melebihi kapasitas BJO ini ({bjo.qty - count_existing} tersisa)."
                )

        return cleaned_data


class PinProtectorBatchForm(forms.Form):
    bjo = forms.ModelChoiceField(queryset=JobHeader.objects.filter(bjo_for='PIN PROTECTOR',is_finish=False), label="Pilih BJO")
    prefix = forms.CharField(label="Prefix")
    start_number = forms.IntegerField(min_value=1, label="Mulai dari")
    end_number = forms.IntegerField(min_value=1, label="Sampai dengan")

    def clean(self):
        cleaned_data = super().clean()
        bjo = cleaned_data.get('bjo')
        start = cleaned_data.get('start_number')
        end = cleaned_data.get('end_number')

        if bjo and start and end:
            count_existing = PinProtector.objects.filter(bjo=bjo).count()
            total_requested = end - start + 1

            if total_requested <= 0:
                raise forms.ValidationError("Nomor akhir harus lebih besar atau sama dengan nomor awal.")

            if count_existing + total_requested > bjo.qty:
                raise forms.ValidationError(
                    f"Jumlah PIN yang akan dibuat ({total_requested}) melebihi kapasitas BJO ini ({bjo.qty - count_existing} tersisa)."
                )

        return cleaned_data


class BoxProtectorBatchForm(forms.Form):
    bjo = forms.ModelChoiceField(queryset=JobHeader.objects.filter(bjo_for='BOX PROTECTOR',is_finish=False), label="Pilih BJO")
    prefix = forms.CharField(max_length=5, label="Prefix (e.g. A)")
    start_number = forms.IntegerField(label="Start Number")
    end_number = forms.IntegerField(label="End Number")

    def clean(self):
        cleaned_data = super().clean()
        bjo = cleaned_data.get('bjo')
        start = cleaned_data.get('start_number')
        end = cleaned_data.get('end_number')

        if bjo and start and end:
            count_existing = PinProtector.objects.filter(bjo=bjo).count()
            total_requested = end - start + 1

            if total_requested <= 0:
                raise forms.ValidationError("Nomor akhir harus lebih besar atau sama dengan nomor awal.")

            if count_existing + total_requested > bjo.qty:
                raise forms.ValidationError(
                    f"Jumlah PIN yang akan dibuat ({total_requested}) melebihi kapasitas BJO ini ({bjo.qty - count_existing} tersisa)."
                )

        return cleaned_data


class PlainTimeInput(Widget):
    def render(self, name, value, attrs=None, renderer=None):
        display = value.strftime('%H:%M:%S') if value else '-'
        return mark_safe(f'<span style="padding:4px 8px;display:inline-block;">{display}</span>')


class ThreadDetailForm(forms.ModelForm):
    joint_number = forms.TypedChoiceField(
        choices=[], coerce=str, required=False, widget=Select2Widget(attrs={'data-width': '100%'})
    )

    class Meta:
        model = ThreadDetail
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Setup joint_number dropdown
        available = SerialNumber.objects.filter(
            Q(is_box_threaded=False) &
            Q(is_pin_threaded=False) 
            # Q(is_phosphated=False)
        ).order_by('joint_number')

        choices = [(s.joint_number, s.joint_number) for s in available]
        current_value = self.instance.joint_number
        if current_value and current_value not in [v for v, _ in choices]:
            choices.insert(0, (current_value, f"{current_value}"))
        self.fields['joint_number'].choices = choices

        # Untuk baris yang sudah tersimpan, jadikan semua field readonly
        if self.instance.pk:
            from .forms import PlainTimeInput  # pastikan import-nya benar

            self.fields['joint_number'].disabled = True
            self.fields['start_time'].widget = PlainTimeInput()
            self.fields['stop_time'].widget = PlainTimeInput()
            for field_name in self.fields:
                if field_name not in ['joint_number', 'start_time', 'stop_time']:
                    self.fields[field_name].disabled = True
    
    

class ThreadDetailInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue

            cleaned = form.cleaned_data
            bjo = cleaned.get('bjo')
            start = cleaned.get('start_time')
            stop = cleaned.get('stop_time')


class PlainTimeInput(Widget):
    def render(self, name, value, attrs=None, renderer=None):
        if value:
            display = value.strftime('%H:%M:%S')
            hidden = f'<input type="hidden" name="{name}" value="{display}"/>'
            readonly = f'<span style="padding:4px 8px; display:inline-block; background:#f7f7f7;">{display}</span>'
        else:
            hidden = f'<input type="hidden" name="{name}" value=""/>'
            readonly = '<span style="padding:4px 8px; display:inline-block;">-</span>'
        return mark_safe(hidden + readonly)