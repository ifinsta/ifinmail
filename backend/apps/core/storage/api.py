"""core.storage — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import upload_file

__all__ = ['upload_file']
