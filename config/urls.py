from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from care import views as care_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("care.api.urls")),
    path("app/", care_views.react_workspace, name="react-workspace"),
    path("", include("care.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
