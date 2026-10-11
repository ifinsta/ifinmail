from django.urls import path

from .api import telemetry_ack, telemetry_errors, telemetry_fingerprints, telemetry_stats

app_name = 'telemetry'

urlpatterns = [
    path('errors/', telemetry_errors, name='errors'),
    path('stats/', telemetry_stats, name='stats'),
    path('fingerprints/', telemetry_fingerprints, name='fingerprints'),
    path('ack/', telemetry_ack, name='ack'),
]
