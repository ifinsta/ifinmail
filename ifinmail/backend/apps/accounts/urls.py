from django.urls import path
from django.views.generic import RedirectView

from .views import dashboard

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='dashboard', permanent=False)),
    path('dashboard/', dashboard, name='dashboard'),
]
