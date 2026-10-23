from django.apps import AppConfig

class ProductionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'production'
    verbose_name = '01. Modul Produksi'  # Ganti sesuai nama menu yang kamu inginkan

    def ready(self):
        import production.signals