from django.db import models
from production.models import *


class BevelHeader(UpperCaseModel):
    date = models.DateField(null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, blank=True, null=True)
    machine_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, blank=True, null=True)
    shift_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, blank=True, null=True)
    operator_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    booked_hours = models.ForeignKey(BookedHours, on_delete=models.CASCADE, blank=True, null=True)
    actual_output = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    actual_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    comment = models.TextField(null=True, blank=True)
    is_posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.machine:
            self.machine_name = self.machine.name
        if self.shift:
            self.shift_name = self.shift.name
        if self.operator:
            self.operator_name = self.operator.name
        super().save(*args, **kwargs)

    @property
    def oee_score(self):
        return calculate_custom_oee(self)
    
    def __str__(self):
        return f"date: {self.date} | machine: {self.machine} | operator: {self.operator} | {self.shift}"
    
    class Meta:
        verbose_name = 'Record Beveling'
        verbose_name_plural = 'Record Beveling'


class BevelDetail(UpperCaseModel):
    Reff = models.ForeignKey(BevelHeader, on_delete=models.CASCADE, blank=True, null=True)
    start_time = models.TimeField(null=True, blank=True)
    stop_time = models.TimeField(null=True, blank=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    job_operation = models.CharField(max_length=3, null=True, blank=True)
    joint_number = models.CharField(max_length=10, blank=True, null=True)
    conn_no = models.CharField(max_length=50, blank=True, null=True)
    ct = models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)
    pb = models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)
    is_uncompleted = models.BooleanField(default=False)
    output = models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.start_time} | {self.stop_time} | {self.bjo} | {self.joint_number}"
    
    class Meta:
        verbose_name = 'Bevel Detail'
        verbose_name_plural = 'Bevel Details'


class BevelNcr(UpperCaseModel):
    serial = models.ForeignKey(BevelDetail, on_delete=models.CASCADE, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    disposition = models.TextField(null=True, blank=True)
    action = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.serial} | {self.reason} | {self.disposition} | {self.action}"
    
    class Meta:
        verbose_name = 'Record Bevel NCR'
        verbose_name_plural = 'Record Bevel NCR'


class BevelConsumsion(UpperCaseModel):
    Reff = models.ForeignKey(BevelHeader, on_delete=models.CASCADE, blank=True, null=True)
    insert_snmg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insert_dnmg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insert_bevel = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    others = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"Bevel Consumption for {self.Reff}"

    class Meta:
        verbose_name = 'Record Bevel Consumption'
        verbose_name_plural = 'Record Bevel Consumption'


class BevelReasonStop(UpperCaseModel):
    Reff = models.ForeignKey(BevelHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    reject = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    cutback = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)  # bisa cutback bisa rework
    maintenance = models.ForeignKey(Maintenance, on_delete=models.CASCADE, blank=True, null=True)
    waiting_materials = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    meeting = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_over = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_over_comment = models.TextField(null=True, blank=True)
    others = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Record Bevel Reason Stop'
        verbose_name_plural = 'Record Bevel Reason Stop'
    
    def __str__(self):
        return f"BJO: {self.bjo_number} | Reject: {self.reject}"