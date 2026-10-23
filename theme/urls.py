from django.urls import path
from theme.views import home_view  # import view-nya

urlpatterns = [
    path('', home_view, name='home'),  # route ke halaman home
]
