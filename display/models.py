from django.db import models
from datetime import date, datetime, time
from production.models import Machine, Shift, Process, JobHeader

class Produksi(models.Model):
    date = models.DateField(blank=True, null=True)
    machine = models.CharField(max_length=50, blank=True, null=True)
    shift = models.CharField(max_length=50, blank=True, null=True)
    operator = models.CharField(max_length=50, blank=True, null=True)
    bjo = models.CharField(max_length=50, blank=True, null=True)
    process = models.CharField(max_length=50, blank=True, null=True)
    ct = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    booking_hours = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    actual_hours = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    output = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    reject = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    non_recordable = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    time_start = models.TimeField(blank=True, null=True)
    time_stop = models.TimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if not self.date:
            self.date = date.today()
        if not self.time_start:
            now = datetime.now()
            self.time_start = time(hour=now.hour, minute=now.minute)
        super().save(*args, **kwargs)

    def __str__(self):
        return super().__str__()
    
    class Meta:
        verbose_name = 'Data Produksi'
        verbose_name_plural = 'Data Produksi'
    

class Data(models.Model):
    date = models.DateField()
    process = models.ForeignKey(Process, on_delete=models.CASCADE, blank=True, null=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, blank=True, null=True)
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, blank=True, null=True)
    booking_hours = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)  # Planned / Booked Hours
    actual_hours = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)   # Operating Hours (auto)
    output = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)         # Actual Output
    ct = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)             # Cycle Time (ideal)
    reject = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)         # Rejects
    non_recordable = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True) # Downtime
    oee = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        try:
            if self.booking_hours and self.booking_hours > 0:
                # --- Actual Hours = Operating Time ---
                self.actual_hours = (self.booking_hours or 0) - (self.non_recordable or 0)

                # --- Availability ---
                availability = max(self.actual_hours / self.booking_hours, 0)

                # --- Performance ---
                if self.actual_hours > 0 and self.ct and self.output:
                    ideal_time = (self.output or 0) * (self.ct or 0)
                    performance = max(ideal_time / self.actual_hours, 0)
                else:
                    performance = 0

                # --- Quality ---
                if self.output and self.output > 0:
                    quality = max(((self.output or 0) - (self.reject or 0)) / self.output, 0)
                else:
                    quality = 0

                # --- OEE ---
                self.oee = round(availability * performance * quality * 100, 2)
            else:
                self.oee = 0
                self.actual_hours = 0
        except ZeroDivisionError:
            self.oee = 0
            self.actual_hours = 0

        super().save(*args, **kwargs)

    def __str__(self):
        return f"date: {self.date} | proses: {self.process} | mesin: {self.machine} | shift: {self.shift} | OEE: {self.oee} | reject: {self.reject} | nr: {self.non_recordable}"
    
    class Meta:
        verbose_name = 'Rekam Data'
        verbose_name_plural = 'Rekam Data'
