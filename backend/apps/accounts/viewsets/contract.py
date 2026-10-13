"""The API's machine-readable contract and a typed catalogue of its operations.

``ContractAPI`` adds ``x-required-scope`` to every operation of the OpenAPI document, taken from
the ``require_scope`` decorator on the handler itself, so the scope an integrator reads is the
scope the server enforces. ``operations()`` gives the same facts as plain data (the assistant and
the tests use it), so there is no second list to keep in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ninja import NinjaAPI

from backend.apps.accounts.viewsets.auth import scope_of


@dataclass(frozen=True)
class OperationInfo:
    method: str  # "GET"
    path: str  # "/mailboxes/{address}", relative to the version's base URL
    summary: str
    scope: str | None  # None only for the anonymous operations
    anonymous: bool
    statuses: tuple[int, ...]
    tags: tuple[str, ...]


def operations(api: NinjaAPI) -> list[OperationInfo]:
    """Every operation of ``api`` in a stable order (path, then method)."""
    found: list[OperationInfo] = []
    for prefix, router in api._routers:  # noqa: SLF001  (Ninja has no public listing)
        for path, view in router.path_operations.items():
            for operation in view.operations:
                statuses = tuple(
                    sorted(code for code in operation.response_models if isinstance(code, int))
                )
                for method in operation.methods:
                    found.append(
                        OperationInfo(
                            method=method,
                            path=f'{prefix}{path}',
                            summary=operation.summary or '',
                            scope=scope_of(operation.view_func),
                            # NOT_SET means the API-wide keys apply; an explicit None is anonymous
                            anonymous=operation.auth_param is None,
                            statuses=statuses,
                            tags=tuple(operation.tags or ()),
                        )
                    )
    return sorted(found, key=lambda o: (o.path, o.method))


class ContractAPI(NinjaAPI):
    """``NinjaAPI`` whose OpenAPI document also states each operation's required scope."""

    def get_openapi_schema(self, *args: Any, **kwargs: Any) -> Any:
        schema = super().get_openapi_schema(*args, **kwargs)
        root = kwargs.get('path_prefix')
        if root is None:
            root = self.get_root_path(kwargs.get('path_params') or {})
        root = str(root).rstrip('/')
        known = {(o.method.lower(), f'{root}{o.path}'): o for o in operations(self)}
        for url, item in schema['paths'].items():
            for method, document in item.items():
                info = known.get((method, url))
                if info is not None and info.scope is not None:
                    document['x-required-scope'] = info.scope
        return schema


__all__ = ['ContractAPI', 'OperationInfo', 'operations']
