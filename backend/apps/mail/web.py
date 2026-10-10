"""mail — web.py: re-export layer for urls.py → web.py → views/ contract."""

from .views import autoconfig_mozilla, autoconfig_outlook, mta_sts_policy

__all__ = ['autoconfig_mozilla', 'autoconfig_outlook', 'mta_sts_policy']
