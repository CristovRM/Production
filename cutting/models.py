from django.db import models
from production.models import JobHeader, SerialNumber, Operator, Shift

class cut_header(models.Model):
    bjo_protector = models.ForeignKey(JobHeader, on_delete=models.CASCADE, blank=True, null=True)
    station = models.CharField(max_length=50, default="CUTTING AREA", null=True, blank=True)
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)


class cut_detail(models.Model):
    reff = models.ForeignKey(cut_header, on_delete=models.CASCADE, null=True, blank=True)
    joint_number = models.CharField(max_length=50, null=True, blank=True) # di entry manual tidak terhubung ke tabel serial number.
    protector_number = models.CharField(max_length=50, null=True, blank=True) # data lookup ke tabel pin ptrotektor atau box protektor berdasarkan bjo
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    modified_at = models.DateTimeField(auto_now=True, blank=True, null=True)

