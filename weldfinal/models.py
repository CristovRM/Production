from django.db import models
from production.models import JobHeader, SerialNumber, Operator, Shift

class weldfinal_header(models.Model):
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)  
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    shift_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, null=True, blank=True)
    operator_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        if self.shift:
            self.shift_name = self.shift.name
        if self.operator:
            self.operator_name = self.operator.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.created_at}"
    
    class Meta:
        verbose_name = 'Weld Final'
        verbose_name_plural = 'Weld Final'

    
class weldfinal_detail(models.Model):
    weldfinal_header = models.ForeignKey(weldfinal_header, on_delete=models.CASCADE, related_name='weldfinal_details', blank=True, null=True)
    joint_number = models.ForeignKey(SerialNumber, on_delete=models.CASCADE, blank=True, null=True)
    joint_number_serial = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    tally = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    bevel_pin = models.BooleanField(default=False)
    bevel_box = models.BooleanField(default=False)
    grind_pin = models.BooleanField(default=False)
    grind_box = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        # Populate denormalized field
        if self.joint_number:
            self.joint_number_serial = self.joint_number.joint_number
        
        # Check completion status - semua proses harus selesai
        self.is_completed = bool(
            self.tally is not None and 
            self.tally > 0 and
            self.bevel_pin and
            self.bevel_box and
            self.grind_pin and
            self.grind_box
        )
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.joint_number} | {self.tally}"