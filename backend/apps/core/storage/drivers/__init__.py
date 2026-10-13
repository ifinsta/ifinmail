"""Storage drivers: the registry of implementations of the storage contract.

A driver is a factory that takes the plugin's settings (a dict of strings) and returns an
``ObjectStore``. Core registers ``local`` and ``s3``; another app can add a protocol with
``register('webdav', factory)`` from its ``AppConfig.ready()`` without core importing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..contract import ObjectStore, StorageRejectedError

Factory = Callable[[Mapping[str, str]], ObjectStore]
_DRIVERS: dict[str, Factory] = {}


def register(name: str, factory: Factory) -> None:
    _DRIVERS[name] = factory


def names() -> list[str]:
    return sorted(_DRIVERS)


def build(name: str, settings: Mapping[str, str]) -> ObjectStore:
    factory = _DRIVERS.get(name)
    if factory is None:
        raise StorageRejectedError(f'No storage driver called "{name}" is installed.')
    return factory(settings)


def _register_builtin() -> None:
    from .local import LocalStore
    from .s3 import S3Store

    register('local', lambda s: LocalStore(s.get('root', '')))
    register('s3', S3Store.from_settings)


_register_builtin()
