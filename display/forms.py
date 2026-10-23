from django import forms
from .models import Produksi
from production.models import Machine, Shift, Operator, JobHeader, Process

class ProduksiForm(forms.ModelForm):
    bjo_obj = forms.ModelChoiceField(
        queryset=JobHeader.objects.all(),
        required=False,
        label="BJO",
    )

    class Meta:
        model = Produksi
        exclude = ['date', 'time_start', 'bjo']  # bjo disembunyikan, karena kita pakai bjo_obj
        widgets = {
            'machine': forms.Select(attrs={'class': 'form-control'}),
            'shift': forms.Select(attrs={'class': 'form-control'}),
            'operator': forms.Select(attrs={'class': 'form-control'}),
            'bjo_obj': forms.Select(attrs={'class': 'form-control'}),
            'process': forms.TextInput(attrs={'class': 'form-control'}),
            'ct': forms.NumberInput(attrs={'class': 'form-control'}),
            'booking_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'actual_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'output': forms.NumberInput(attrs={'class': 'form-control'}),
            'reject': forms.NumberInput(attrs={'class': 'form-control'}),
            'non_recordable': forms.NumberInput(attrs={'class': 'form-control'}),
            'time_stop': forms.TimeInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['machine'] = forms.ChoiceField(choices=[
            (m.name, m.name) for m in Machine.objects.all()
        ], required=False)

        self.fields['shift'] = forms.ChoiceField(choices=[
            (s.name, s.name) for s in Shift.objects.all()
        ], required=False)

        self.fields['operator'] = forms.ChoiceField(choices=[
            (o.name, o.name) for o in Operator.objects.all()
        ], required=False)

        self.fields['process'] = forms.ChoiceField(choices=[
            (p.name, p.name) for p in Process.objects.all()
        ], required=False)

        self.fields['bjo_obj'].label_from_instance = lambda obj: str(obj)

    def save(self, commit=True):
        instance = super().save(commit=False)
        bjo_obj = self.cleaned_data.get('bjo_obj')
        if bjo_obj:
            instance.bjo = bjo_obj.bjo  # hanya simpan nomor BJO
        if commit:
            instance.save()
        return instance
