from django.apps import AppConfig


class PhospateConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'phosphate'
    verbose_name = '02. Modul Phosphate'

    def ready(self):
        import phosphate.signals