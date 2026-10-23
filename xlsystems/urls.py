from django.contrib import admin
from django.urls import path, include
from accounts.views import CustomLoginView, landing_page, CustomLogoutView
from django.conf.urls.static import static
from django.conf import settings
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('dashboard/', landing_page, name='dashboard'),
    path('production/', include('production.urls')),
    path('info/', include('display.urls')),
    path('phosphate/', include('phosphate.urls')),
    path('theme/', include('theme.urls')),
    path('accounts/', include('accounts.urls')),
    path('cutting/', include('cutting.urls')),
    path('bevel/', include('bevel.urls')),
    path('weldfinal/', include('weldfinal.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)