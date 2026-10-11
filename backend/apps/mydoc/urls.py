"""
MyDoc URL Configuration

Provides: documentation pages, OpenAPI export, search, and cache management.
"""

from django.urls import path

from .views import (
    MyDocAuditView,
    MyDocCacheInvalidateView,
    MyDocEndpointView,
    MyDocIndexView,
    MyDocOpenAPIView,
    MyDocReportView,
    MyDocSearchView,
    MyDocSectionView,
)

app_name = "mydoc"

urlpatterns = [
    path("", MyDocIndexView.as_view(), name="index"),
    path("search/", MyDocSearchView.as_view(), name="search"),
    path("audit/", MyDocAuditView.as_view(), name="audit"),
    path("audit/report/", MyDocReportView.as_view(), name="audit-report"),
    path("openapi.json", MyDocOpenAPIView.as_view(), name="openapi"),
    path("cache/invalidate/", MyDocCacheInvalidateView.as_view(), name="cache-invalidate"),
    path("<slug:section_slug>/", MyDocSectionView.as_view(), name="section"),
    path(
        "<slug:section_slug>/<slug:endpoint_slug>/",
        MyDocEndpointView.as_view(),
        name="endpoint",
    ),
]
