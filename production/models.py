from django.db import models
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from .services import calculate_custom_oee

class UpperCaseModel(models.Model):
    class Meta:
        abstract = True  # supaya tidak membuat tabel sendiri

    def save(self, *args, **kwargs):
        for field in self._meta.fields:
            if isinstance(field, (models.CharField, models.TextField)):
                value = getattr(self, field.name, None)
                if isinstance(value, str):
                    setattr(self, field.name, value.upper())
        super().save(*args, **kwargs)


class Connection(UpperCaseModel): #viper, xlc, xlw, xlcs, xlwgt, etc.
    name = models.CharField(max_length=50, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = 'Master Data Connector'
        verbose_name_plural = 'Master Data Connector'
    

class Process(UpperCaseModel): # threading and welding
    name = models.CharField(max_length=30, null=True, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f" {self.name}"
    
    class Meta:
        verbose_name = 'Master Data Proses'
        verbose_name_plural = 'Master Data Proses'
    
    
class MaterialGrade(UpperCaseModel): # if process welding must choice this. M70 or M95
    name = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = 'Master Data Grade'
        verbose_name_plural = 'Master Data Grade'
    

class Machine(UpperCaseModel):  # NB48, Insitu 1 & 2, VTLEX 1 & 2, SR1.2.3, ESAP 1 & 2.
    name = models.CharField(max_length=50, null=True, blank=True)
    process_type = models.ForeignKey('Process', on_delete=models.CASCADE, blank=True, null=True)
    machine_capacity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = 'Master Data Mesin'
        verbose_name_plural = 'Master Data Mesin'
    
    
class Maintenance(UpperCaseModel):
    machine = models.ForeignKey('ThreadHeader', on_delete=models.CASCADE, blank=True, null=True)
    weld_machine = models.ForeignKey('WeldHeader', on_delete=models.CASCADE, blank=True, null=True)
    bevel_machine = models.ForeignKey('bevel.BevelHeader', on_delete=models.CASCADE, blank=True, null=True)
    bjo = models.ForeignKey('JobHeader', on_delete=models.CASCADE, blank=True, null=True)
    issue = models.TextField(null=True, blank=True)
    duration = models.DecimalField(max_digits=5, decimal_places=2)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def clean(self):
        refs = sum([bool(self.machine), bool(self.weld_machine), bool(self.bevel_machine)])
        if refs > 1:
            raise ValidationError("Maintenance hanya boleh mengacu ke satu header saja")
        if refs == 0:
            raise ValidationError("Maintenance harus mengacu ke salah satu header")
    
    @property
    def related_header(self):
        """Property untuk mendapatkan header yang terkait"""
        if self.machine:
            return self.machine
        elif self.weld_machine:
            return self.weld_machine
        elif self.bevel_machine:
            return self.bevel_machine
        return None
    
    @property
    def process_type(self):
        """Property untuk mendapatkan tipe process"""
        if self.machine:
            return "THREAD"
        elif self.weld_machine:
            return "WELD"
        elif self.bevel_machine:
            return "BEVEL"
        return None
    
    def __str__(self):
        header = self.related_header
        return f"{header} | {self.issue} | {self.duration}"
    
    class Meta:
        verbose_name = 'Master Data Maintenance'
        verbose_name_plural = 'Master Data Maintenance'
    
    
class OdThickness(UpperCaseModel): # OD Thickness
    od = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    wall = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    size = models.CharField(max_length=50, null=True, blank=True)
    process_type = models.ForeignKey(Process, on_delete=models.CASCADE, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.process_type} {self.size}"
    
    class Meta:
        verbose_name = 'Master Data OD Thickness'
        verbose_name_plural = 'Master Data OD Thickness'
    

class InfoTag(models.Model): # PxB, PxP, etc
    name = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.name}"
    
    class Meta:
        verbose_name = 'Master Data Info Tag'
        verbose_name_plural = 'Master Data Info Tag'
    

class CycleTime(UpperCaseModel):
    process_type = models.ForeignKey(Process, on_delete=models.CASCADE, blank=True, null=True)
    od_thickness = models.ForeignKey(OdThickness, on_delete=models.CASCADE, blank=True, null=True)
    ct_for = models.ForeignKey(MaterialGrade, on_delete=models.CASCADE, blank=True, null=True)
    hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    info_product = models.CharField(max_length=30, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.od_thickness} | {self.ct_for} | hours: {self.hours} | cost: ${self.cost}"
    
    class Meta:
        verbose_name = 'Master Data Cycle Time'
        verbose_name_plural = 'Master Data Cycle Time'
    
        
class BookedHours(UpperCaseModel): # Normal, Over Time, Friday Normal, Friday Overtime.
    name = models.CharField(max_length=50, null=True, blank=True)
    duration = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.name} | duration: {self.duration} hours"
    
    class Meta:
        verbose_name = 'Master Data Booking Hours'
        verbose_name_plural = 'Master Data Booking Hours'
    

class JobHeader(UpperCaseModel):
    bjo = models.CharField(max_length=50, null=True, blank=True)
    bt = models.CharField(max_length=50, null=True, blank=True)
    customer = models.CharField(max_length=50, null=True, blank=True)
    process_type = models.ForeignKey(Process, on_delete=models.CASCADE, null=True, blank=True)
    size = models.ForeignKey(OdThickness, on_delete=models.CASCADE, blank=True, null=True)
    conn = models.ForeignKey(Connection, on_delete=models.CASCADE, blank=True, null=True)
    info = models.ForeignKey(InfoTag, on_delete=models.CASCADE, blank=True, null=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ct_reference = models.ForeignKey(MaterialGrade, on_delete=models.CASCADE, blank=True, null=True)
    product = models.CharField(max_length=255, null=True, blank=True)
    bjo_for = models.CharField(max_length=20, choices=[('PIPE','PIPE'),('BOX PROTECTOR','BOX PROTECTOR'),('PIN PROTECTOR','PIN PROTECTOR')], blank=True, null=True)
    lube = models.CharField(max_length=255, null=True, blank=True) # tambahan informasi lube untuk laporan XL100.
    is_composite = models.BooleanField(default=False, verbose_name='Composite')
    type_order = models.CharField(max_length=255, choices=[
        ('XL-100AB-1 REV 0','XL-100AB-1 REV 0'),
        ('XL-100AB-2 REV 0','XL-100AB-2 REV 0'),
        ('XL-100AB-3 REV 0','XL-100AB-3 REV 0'),
        ('XL-100BB-1 REV 0','XL-100BB-1 REV 0'),
        ('XL-100BB-2.1 REV 0','XL-100BB-2.1 REV 0'),
        ('XL-100BB-2.2 REV 0','XL-100BB-2.2 REV 0'),
        ('XL-100BB-2.3 REV 0','XL-100BB-2.3 REV 0'),
        ], 
        null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_finish = models.BooleanField(null=True, blank=True, default=False)
    finish_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    @property
    def total_finished(self):
        related_details = self.jobdetail_set.all()
        total = sum(detail.finished or 0 for detail in related_details)
        return total
    
    @property
    def remaining_qty(self):
        if self.qty is None:
            return "N/A"
        remaining = self.qty - self.total_finished
        return max(remaining, 0)  # biar nggak minus kalau overfinished

    def __str__(self):
        return f"bjo: {self.bjo} | customer: {self.customer} | {self.size} | {self.info} | qty: {self.qty} joints"
    
    class Meta:
        verbose_name = '01. Batam Job Order'
        verbose_name_plural = '01. Batam Job Order'

    
class jobDetail(UpperCaseModel):
    job = models.ForeignKey(JobHeader,on_delete=models.CASCADE, null=True, blank=True)
    box = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pin = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fc = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    finished = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def clean(self):
        super().clean()
        if self.finished and self.job and self.finished > self.job.qty:
            raise ValidationError("Jumlah finished tidak boleh melebihi qty di JobHeader.")

    def __str__(self):
        return f"{self.job} | box: {self.box} | pin: {self.pin} | fs: {self.fs} | fc: {self.fc} | finished: {self.finished} joints"
    
  
class PriceBook(UpperCaseModel):
    process_type = models.ForeignKey(Process, on_delete=models.CASCADE, blank=True, null=True)
    od_thickness = models.ForeignKey(OdThickness, on_delete=models.CASCADE, blank=True, null=True)
    pb_for = models.ForeignKey(MaterialGrade, on_delete=models.CASCADE, blank=True, null=True)
    time_in_h = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_per_end = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_per_joint = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_vtl = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.od_thickness} | time in hours: {self.time_in_h} | cost: ${self.cost_weld_usd}"
    
    class Meta:
        verbose_name = 'Master Data Price Book'
        verbose_name_plural = 'Master Data Price Book'
    

class Shift(UpperCaseModel):
    name = models.CharField(max_length=50, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    def __str__(self):
        return f"{self.name}"
    
    class Meta:
        verbose_name = 'Master Data Shift'
        verbose_name_plural = 'Master Data Shift'
    

class Operator(UpperCaseModel):
    employee_id = models.CharField(max_length=50, null=True, blank=True)
    initial = models.CharField(max_length=50, null=True, blank=True)
    name = models.CharField(max_length=50, null=True, blank=True)
    position = models.CharField(max_length=50, choices=[('THREAD','THREAD'),('WELD','WELD')], null=True, blank=True)
    work_station = models.CharField(max_length=50, choices=[('NB48','NB48'),('INS-1','INS-1'),('INS-2','INS-2'),('VTLEX','VTLEX'),('OKUMA','OKUMA'),('PHOSPHATE NB','PHOSPHATE NB'),('PHOSPHATE INS-1','PHOSPHATE INS-1'),('PHOSPHATE PROTECTOR','PHOSPHATE PROTECTOR'),('SR-1','SR-1'),('SR-2','SR-2'),('SR-3','SR-3'),('ESAB','ESAB'),('LINCOLN','LINCOLN'),('SANDING','SANDING'),('FINISHING','FINISHING')], null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = 'Master Data Operator'
        verbose_name_plural = 'Master Data Operator'
    

class SerialNumber(UpperCaseModel):
    bjo = models.ForeignKey(JobHeader, on_delete=models.PROTECT, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    joint_number = models.CharField(max_length=10, null=True, blank=True)
    is_box_threaded = models.BooleanField(blank=True, null=True, default=False)
    is_pin_threaded = models.BooleanField(blank=True, null=True, default=False)
    is_box_phosphated = models.BooleanField(blank=True, null=True, default=False)
    is_pin_phosphated = models.BooleanField(blank=True, null=True, default=False)
    is_fs_welded = models.BooleanField(blank=True, null=True, default=False)
    is_fcbs_welded = models.BooleanField(blank=True, null=True, default=False)
    is_fcps_welded = models.BooleanField(blank=True, null=True, default=False)
    is_bp_installed = models.BooleanField(blank=True, null=True, default=False)
    is_pp_installed = models.BooleanField(blank=True, null=True, default=False)
    is_beveled = models.BooleanField(blank=True, null=True, default=False)
    is_used = models.BooleanField(blank=True, null=True, default=False)
    is_ncr = models.BooleanField(blank=True, null=True, default=False)
    is_rwk = models.BooleanField(blank=True, null=True, default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.joint_number or f"SN-{self.id}"
    
    class Meta:
        verbose_name = '02. Buat Joint Number'
        verbose_name_plural = '02. Buat Joint Number'
    

class PinProtector(UpperCaseModel):
    bjo = models.ForeignKey(JobHeader, on_delete=models.PROTECT, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)  # ✅ TAMBAH
    serial_number = models.CharField(max_length=10, null=True, blank=True)
    is_threaded = models.BooleanField(blank=True, null=True, default=False)
    is_beveled = models.BooleanField(blank=True, null=True, default=False)
    is_ncr = models.BooleanField(blank=True, null=True, default=False)
    is_rwk = models.BooleanField(blank=True, null=True, default=False)
    is_used = models.BooleanField(blank=True, null=True, default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.serial_number or f"SN-{self.id}"
    
    class Meta:
        verbose_name = '04. Buat No. PIN Protector'
        verbose_name_plural = '04. Buat No. PIN Protector'
    

class BoxProtector(UpperCaseModel):
    bjo = models.ForeignKey(JobHeader, on_delete=models.PROTECT, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)  # ✅ TAMBAH
    serial_number = models.CharField(max_length=10, null=True, blank=True)
    is_threaded = models.BooleanField(blank=True, null=True, default=False)
    is_beveled = models.BooleanField(blank=True, null=True, default=False)
    is_ncr = models.BooleanField(blank=True, null=True, default=False)
    is_rwk = models.BooleanField(blank=True, null=True, default=False)
    is_used = models.BooleanField(blank=True, null=True, default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.serial_number or f"SN-{self.id}"
    
    class Meta:
        verbose_name = '03. Buat No. BOX Protector'
        verbose_name_plural = '03. Buat No. BOX Protector'


class ThreadHeader(UpperCaseModel):
    date = models.DateField(null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, blank=True, null=True)
    machine_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    shift = models.ForeignKey('Shift', on_delete=models.CASCADE, blank=True, null=True)
    shift_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    operator = models.ForeignKey('Operator', on_delete=models.CASCADE, blank=True, null=True)
    operator_name = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    booked_hours = models.ForeignKey('BookedHours', on_delete=models.CASCADE, blank=True, null=True)
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
        verbose_name = 'Record Threading'
        verbose_name_plural = 'Record Threading'
    

class ThreadDetail(UpperCaseModel):
    Reff = models.ForeignKey(ThreadHeader, on_delete=models.CASCADE, blank=True, null=True)
    start_time = models.TimeField(null=True, blank=True)
    stop_time = models.TimeField(null=True, blank=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    job_operation = models.CharField(max_length=3, null=True, blank=True)
    joint_number = models.CharField(max_length=10, blank=True, null=True)
    pin_or_box = models.CharField(max_length=50, null=True, blank=True, choices=[('PIN','PIN'),('BOX','BOX')])
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
        return f"{self.start_time} | {self.stop_time} | {self.bjo} | {self.joint_number} | {self.pin_or_box}"
    
    
class ThreadNcr(UpperCaseModel):
    serial = models.ForeignKey(ThreadDetail, on_delete=models.CASCADE, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    disposition = models.TextField(null=True, blank=True)
    action = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.serial} | {self.reason} | {self.disposition} | { self.action}"
    
    class Meta:
        verbose_name = 'Record Threading NCR'
        verbose_name_plural = 'Record Threading NCR'
    

class ThreadConsumsion(UpperCaseModel):
    Reff = models.ForeignKey(ThreadHeader, on_delete=models.CASCADE, blank=True, null=True)
    insert_snmg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insert_dnmg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insert_threading = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    others = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta:
        verbose_name = 'Record Threading Consumption'
        verbose_name_plural = 'Record Threading Consumption'


class TreadReasonStop(UpperCaseModel):
    Reff = models.ForeignKey(ThreadHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    joint_number = models.CharField(max_length=10, blank=True, null=True)
    reject =  models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    cutback = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0) # bisa cutback bisa rework
    maintenance =  models.ForeignKey(Maintenance, on_delete=models.CASCADE, blank=True, null=True)
    waiting_materials =  models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    meeting = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_over = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_over_comment = models.TextField(null=True, blank=True)
    others =  models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rejected_joints = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Record Threading Reason Stop'
        verbose_name_plural = 'Record Threading Reason Stop'
    
    def __str__(self):
        return f"BJO: {self.bjo_number} | Reject: {self.reject}"


class WeldHeader(UpperCaseModel):
    date = models.DateField(null=True, blank=True)
    machine = models.ForeignKey(Machine,on_delete=models.CASCADE, blank=True, null=True)
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, blank=True, null=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, blank=True, null=True)
    booked_hours = models.ForeignKey(BookedHours, on_delete=models.CASCADE, blank=True, null=True)
    actual_output = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    actual_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    comment = models.TextField(null=True, blank=True)
    is_posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    @property
    def oee_score(self):
        return calculate_custom_oee(self)
    
    def __str__(self):
        return f"date: {self.date} | machine: {self.machine} | operator: {self.operator} | {self.shift}"
    
    class Meta:
        verbose_name = 'Record Welding'
        verbose_name_plural = 'Record Welding'


class WeldDetail(UpperCaseModel):
    Reff = models.ForeignKey(WeldHeader, on_delete=models.CASCADE, blank=True, null=True)
    start_time = models.TimeField(null=True, blank=True)
    stop_time = models.TimeField(null=True, blank=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    job_operation = models.CharField(max_length=3, null=True,blank=True)
    pin_or_box = models.CharField(max_length=50, null=True, blank=True, choices=[('PIN','PIN'),('BOX','BOX'),('FLOAT SHOE','FLOAT SHOE'),('FLOAT COLAR PIN SIDE','FLOAT COLAR PIN SIDE'),('FLOAT COLAR BOX SIDE','FLOAT COLAR BOX SIDE')])
    ct = models.DecimalField(decimal_places=2, max_digits=5, null=True,blank=True)
    joint_number = models.CharField(max_length=10, blank=True, null=True)
    conn_number = models.CharField(max_length=10, blank=True, null=True)
    is_uncompleted = models.BooleanField(default=False)
    output = models.DecimalField(decimal_places=3, max_digits=6, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.start_time} | {self.stop_time} | {self.bjo} | {self.joint_number} | {self.pin_or_box}"
    
    
class WeldNcr(UpperCaseModel):
    serial = models.ForeignKey(WeldDetail, on_delete=models.CASCADE, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    disposition = models.TextField(null=True, blank=True)
    action = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.serial} | {self.reason} | {self.disposition} | { self.action}"
    
    class Meta:
        verbose_name = 'Record Welding NCR'
        verbose_name_plural = 'Record Welding NCR'
    

class WeldConsumsion(UpperCaseModel):
    Reff = models.ForeignKey(WeldHeader, on_delete=models.CASCADE, blank=True, null=True)
    wire = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    flux = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    granding = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cutting = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    others = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta:
        verbose_name = 'Record Welding Comsumtion'
        verbose_name_plural = 'Record Welding Comsumtion'


class WeldReasonStop(UpperCaseModel):
    Reff = models.ForeignKey(WeldHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)           # ✅ BARU
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)            # ✅ BARU
    joint_number = models.CharField(max_length=10, blank=True, null=True)                         # ✅ BARU
    reject = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    cutback = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    maintenance = models.ForeignKey(Maintenance, on_delete=models.CASCADE, blank=True, null=True)
    waiting_materials = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    meeting = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_over = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)     # ✅ BARU
    change_over_comment = models.TextField(null=True, blank=True)                                 # ✅ BARU
    others = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rejected_joints = models.TextField(null=True, blank=True)                                     # ✅ BARU
 
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
 
    def save(self, *args, **kwargs):
        if self.bjo:
            self.bjo_number = self.bjo.bjo
        super().save(*args, **kwargs)
 
    class Meta:
        verbose_name = 'Record Welding Reason Stop'
        verbose_name_plural = 'Record Welding Reason Stop'
 
    def __str__(self):
        bjo_str = f" | BJO: {self.bjo_number}" if self.bjo_number else " | Shared"
        return f"Reff: {self.Reff}{bjo_str} | Reject: {self.reject}"

class Connector(UpperCaseModel):
    """Model untuk menyimpan data connector number"""
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    joint_number = models.CharField(max_length=50, null=True, blank=True)
    conn_number = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def __str__(self):
        return f"{self.joint_number} - {self.conn_number}" if self.joint_number and self.conn_number else f"CONN-{self.id}"
    
    class Meta:
        verbose_name = 'Connector Number'
        verbose_name_plural = 'Connector Number'