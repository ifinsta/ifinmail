"""core — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import delete_setting, get_setting, set_setting

__all__ = ['delete_setting', 'get_setting', 'set_setting']
