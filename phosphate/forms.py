from django import forms
from .models import *
from production.models import *
from django_select2.forms import Select2Widget
from django.forms.models import BaseInlineFormSet


# kode form pin protektor
class PinHeaderForm(forms.ModelForm):
    class Meta:
        model = PinHeader
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bjo'].queryset = JobHeader.objects.filter(bjo_for='PIN PROTECTOR', is_finish=False)

# kode form box protektor
class BoxHeaderForm(forms.ModelForm):
    class Meta:
        model = BoxHeader
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bjo'].queryset = JobHeader.objects.filter(bjo_for='BOX PROTECTOR', is_finish=False)


# kode form installed protektor
class PipeHeaderForm(forms.ModelForm):
    class Meta:
        model = PipeHeader
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bjo'].queryset = JobHeader.objects.filter(bjo_for='PIPE', is_finish=False)



class PipeDetailInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for form in self.forms:
            # Hapus field boolean dan datetime dari form
            for field_name in ['is_box_completed', 'is_pin_completed', 'is_completed', 'created_at', 'modified_at']:
                if field_name in form.fields:
                    del form.fields[field_name]

            instance = form.instance
            if instance.pk:  # Baris lama (edit)
                if instance.is_completed:
                    for field in form.fields:
                        form.fields[field].disabled = True
                elif instance.is_box_completed:
                    if 'box_protector' in form.fields:
                        form.fields['box_protector'].disabled = True
                elif instance.is_pin_completed:
                    if 'pin_protector' in form.fields:
                        form.fields['pin_protector'].disabled = True


# kode form Phosphate Pipa
class PipePhosphateHeaderForm(forms.ModelForm):
    class Meta:
        model = PipePhosphateHeader
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bjo'].queryset = JobHeader.objects.filter(bjo_for='PIPE', is_finish=False)




class PipePhosphateDetailForm(forms.ModelForm):
    class Meta:
        model = PipePhosphateDetail
        exclude = ['box_phosphated', 'pin_phosphated', 'created_at', 'modified_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Ambil parent header dari instance
        parent = self.instance.pipephosphate_header
        if parent and parent.bjo:
            self.fields['joint_number'].queryset = SerialNumber.objects.filter(bjo=parent.bjo)
        else:
            self.fields['joint_number'].queryset = SerialNumber.objects.none()


