"""
Root URL configuration for ifinmail.
"""
from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from django.views.defaults import page_not_found, server_error


def health_check(request):
    """Health check endpoint for load balancers and monitoring."""
    from django.db import connections
    from django.db.utils import OperationalError

    status = {"status": "ok", "database": "ok"}
    try:
        connections["default"].cursor()
    except OperationalError:
        status["database"] = "unreachable"
        status["status"] = "degraded"

    http_status = 200 if status["status"] == "ok" else 503
    return JsonResponse(status, status=http_status)


urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('admin/', include('backend.apps.accounts.urls')),
    path('django-admin/', admin.site.urls),
    path('mail/', include('backend.apps.mail.urls')),
]

# Custom error handlers
handler404 = 'backend.config.urls.custom_404'
handler500 = 'backend.config.urls.custom_500'


def custom_404(request, exception=None):
    return JsonResponse(
        {"error": "Not found", "detail": str(exception) if exception else "Resource not found"},
        status=404,
    )


def custom_500(request):
    return JsonResponse(
        {"error": "Internal server error", "detail": "An unexpected error occurred"},
        status=500,
    )
