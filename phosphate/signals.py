from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import *

@receiver(post_save, sender=PinDetail)
def update_pin_protector_status(sender, instance, created, **kwargs):
    if instance.is_phosphated and instance.protector_number:
        protector = instance.protector_number
        protector.is_used = True
        protector.save()

@receiver(post_save, sender=BoxDetail)
def update_box_protector_status(sender, instance, created, **kwargs):
    if instance.is_phosphated and instance.protector_number:
        protector = instance.protector_number
        protector.is_used = True
        protector.save()


@receiver(post_save, sender=PipeDetail)
def update_installed_status(sender, instance, created, **kwargs):
    # Update pin protector
    if instance.pin_protector and not instance.pin_protector.is_installed:
        instance.pin_protector.is_installed = True
        if instance.joint_number:
            instance.pin_protector.installed_to = instance.joint_number
        instance.pin_protector.save()

    # Update box protector
    if instance.box_protector:
        if not instance.box_protector.is_installed:
            instance.box_protector.is_installed = True
        if instance.joint_number:
            instance.box_protector.installed_to = instance.joint_number
        instance.box_protector.save()

