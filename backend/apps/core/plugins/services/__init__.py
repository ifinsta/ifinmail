"""Plugin services: the single interface to plugin models (see AGENTS.md)."""

from backend.apps.core.plugins.services.catalog import CatalogEntry, CatalogService
from backend.apps.core.plugins.services.lifecycle import InstallationService, OperationResult
from backend.apps.core.plugins.services.submissions import SubmissionService

__all__ = [
    'CatalogEntry',
    'CatalogService',
    'InstallationService',
    'OperationResult',
    'SubmissionService',
]
