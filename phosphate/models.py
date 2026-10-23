from django.db import models
from production.models import JobHeader, SerialNumber, PinProtector, BoxProtector, Operator, Shift


class BoxHeader(models.Model):
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    station = models.CharField(max_length=50, choices=[('NB 48','NB 48'),('INS 1','INS 1'),('DIPPING TANK','DIPPING TANK')], null=True, blank=True)
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
        verbose_name = '01. BOX Protektor'
        verbose_name_plural = '01. BOX Protektor'


class BoxDetail(models.Model):
    box_header = models.ForeignKey(BoxHeader, on_delete=models.CASCADE, related_name='box_details', blank=True, null=True)
    protector_number = models.ForeignKey(BoxProtector, on_delete=models.CASCADE, blank=True, null=True)
    protector_serial = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    is_phosphated = models.BooleanField(default=False)
    is_installed = models.BooleanField(default=False)
    installed_to = models.ForeignKey(SerialNumber, null=True, blank=True, on_delete=models.SET_NULL)
    installed_joint_number = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.is_phosphated = True
        
        if self.protector_number:
            self.protector_serial = self.protector_number.serial_number
        
        if self.installed_to:
            self.installed_joint_number = self.installed_to.joint_number
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.protector_number}"
    

class PinHeader(models.Model):
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    station = models.CharField(max_length=50, choices=[('NB 48','NB 48'),('INS 1','INS 1'),('DIPPING TANK','DIPPING TANK')], null=True, blank=True)
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
        verbose_name = '02. PIN Protektor'
        verbose_name_plural = '02. PIN Protektor'
    

class PinDetail(models.Model):
    pin_header = models.ForeignKey(PinHeader, on_delete=models.CASCADE, related_name='pin_details', blank=True, null=True)   
    protector_number = models.ForeignKey(PinProtector, on_delete=models.CASCADE, blank=True, null=True)
    protector_serial = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    is_phosphated = models.BooleanField(default=False)
    is_installed = models.BooleanField(default=False)
    installed_to = models.ForeignKey(SerialNumber, null=True, blank=True, on_delete=models.SET_NULL)
    installed_joint_number = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.is_phosphated = True
        
        if self.protector_number:
            self.protector_serial = self.protector_number.serial_number
        
        if self.installed_to:
            self.installed_joint_number = self.installed_to.joint_number
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.protector_number}"
    

class PipePhosphateHeader(models.Model):
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    station = models.CharField(max_length=50, choices=[('NB 48','NB 48'),('INS 1','INS 1'),('DIPPING TANK','DIPPING TANK')], null=True, blank=True)
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
        verbose_name = '03. PIPE'
        verbose_name_plural = '03. PIPE'


class PipePhosphateDetail(models.Model):
    pipephosphate_header = models.ForeignKey(PipePhosphateHeader, on_delete=models.CASCADE, related_name='pipephosphate_details', blank=True, null=True)
    joint_number = models.ForeignKey(SerialNumber, on_delete=models.CASCADE, blank=True, null=True)
    joint_number_serial = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    side_phosphate = models.CharField(max_length=50, choices=[('BOX','BOX'),('PIN','PIN')])
    box_phosphated = models.BooleanField(null=True, blank=True, default=False)
    pin_phosphated = models.BooleanField(null=True, blank=True, default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if self.side_phosphate == 'BOX':
            self.box_phosphated = True
            self.pin_phosphated = False
        elif self.side_phosphate == 'PIN':
            self.pin_phosphated = True
            self.box_phosphated = False
        
        if self.joint_number:
            self.joint_number_serial = self.joint_number.joint_number
        
        super().save(*args, **kwargs)


class PipeHeader(models.Model):
    bjo = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    bjo_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)  
    station = models.CharField(max_length=50, choices=[('NB 48','NB 48'),('INS 1','INS 1'),('DIPPING TANK','DIPPING TANK')], null=True, blank=True)
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
        verbose_name = '04. Install Protektor'
        verbose_name_plural = '04. Install Protektor'

    
class PipeDetail(models.Model):
    pipe_header = models.ForeignKey(PipeHeader, on_delete=models.CASCADE, related_name='pipe_details', blank=True, null=True)
    joint_number = models.ForeignKey(SerialNumber, on_delete=models.CASCADE, blank=True, null=True)
    joint_number_serial = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    box_protector = models.ForeignKey(BoxDetail, on_delete=models.CASCADE, blank=True, null=True)
    box_installed_by = models.CharField(max_length=50, blank=True, null=True)
    pin_protector = models.ForeignKey(PinDetail, on_delete=models.CASCADE, blank=True, null=True)
    pin_installed_by = models.CharField(max_length=50, blank=True, null=True)
    tally = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    is_box_completed = models.BooleanField(default=False)
    is_pin_completed = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        # Populate denormalized field
        if self.joint_number:
            self.joint_number_serial = self.joint_number.joint_number
        
        # Update status protektor
        self.is_box_completed = bool(self.box_protector)
        self.is_pin_completed = bool(self.pin_protector)
        
        self.is_completed = bool(
            self.box_protector and 
            self.pin_protector and 
            self.tally is not None and 
            self.tally > 0
        )

        # Simpan diri sendiri dulu
        super().save(*args, **kwargs)

        # Update ke SerialNumber
        if self.joint_number:
            if self.box_protector:
                self.joint_number.is_bp_installed = True
            if self.pin_protector:
                self.joint_number.is_pp_installed = True
            if self.is_completed and not self.joint_number.is_used:
                self.joint_number.is_used = True
            self.joint_number.save(update_fields=['is_bp_installed', 'is_pp_installed', 'is_used'])

        # Update protektor BOX
        if self.box_protector:
            if not self.box_protector.is_installed:
                self.box_protector.is_installed = True
            if self.joint_number:
                self.box_protector.installed_to = self.joint_number
            self.box_protector.save()

        # Update protektor PIN
        if self.pin_protector:
            if not self.pin_protector.is_installed:
                self.pin_protector.is_installed = True
            if self.joint_number:
                self.pin_protector.installed_to = self.joint_number
            self.pin_protector.save()

    def __str__(self):
        return f"{self.joint_number} | {self.pin_protector} | {self.box_protector} | {self.tally}"

    
