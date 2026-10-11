from django.urls import path

from .api import dns_configure, dns_status, dns_verify_domain  # API flow (JSON endpoints)
from .views.server import (
    dns_publish,
    dns_record_add,
    dns_record_delete,
    dns_secondaries,
    dns_server_page,
    dns_zone_mode,
    dns_zone_page,
)
from .web import (  # web flow (template-rendering)
    dns_config_page,
    dns_export_records,
    dns_register_domain,
    dns_set_hop_count,
    dns_toggle_proxy,
    dns_toggle_relay,
)

app_name = 'dns'

urlpatterns = [
    path('', dns_config_page, name='config'),
    path('configure/', dns_configure, name='configure'),
    path('status/', dns_status, name='status'),
    path('register/', dns_register_domain, name='register'),
    path('verify-domain/', dns_verify_domain, name='verify_domain'),
    path('export/', dns_export_records, name='export'),
    path('toggle-proxy/', dns_toggle_proxy, name='toggle_proxy'),
    path('toggle-relay/', dns_toggle_relay, name='toggle_relay'),
    path('set-hop-count/', dns_set_hop_count, name='set_hop_count'),
    path('server/', dns_server_page, name='server'),
    path('server/publish/', dns_publish, name='publish'),
    path('server/secondaries/', dns_secondaries, name='secondaries'),
    path('server/records/add/', dns_record_add, name='record_add'),
    path('server/records/delete/', dns_record_delete, name='record_delete'),
    path('server/mode/', dns_zone_mode, name='zone_mode'),
    path('server/<str:zone>/', dns_zone_page, name='zone'),
]
