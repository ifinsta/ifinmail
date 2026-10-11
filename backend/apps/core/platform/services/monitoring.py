"""Monitoring service — reads monitor data, validates DNS, checks system health."""

import json
import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime
from typing import Any

from django.core.cache import cache

from backend.config.env import primary_domain

logger = logging.getLogger('backend')

_LETSENCRYPT_DIR = os.environ.get('LETSENCRYPT_DIR', '/etc/letsencrypt')
_MAIL_VHOSTS_DIR = os.environ.get('MAIL_VHOSTS_DIR', '/var/mail/vhosts')
_APP_DIR = os.environ.get('APP_DIR', '/app')


class MonitoringService:
    CACHE_KEY_LATEST = 'ifinmail:monitor:latest'
    CACHE_KEY_DNS = 'ifinmail:monitor:dns'
    CACHE_TIMEOUT = 600

    @staticmethod
    def get_latest_report() -> dict[str, Any] | None:
        try:
            data = cache.get(MonitoringService.CACHE_KEY_LATEST)
            if data:
                return json.loads(data) if isinstance(data, str) else data
        except Exception:
            logger.exception('Failed to read monitoring report from cache')
        return None

    @staticmethod
    def get_service_status() -> dict[str, Any]:
        report = MonitoringService.get_latest_report()
        if report is None:
            return {'status': 'unknown', 'services': {}}
        return {
            'status': report.get('overall', 'unknown'),
            'services': report.get('services', {}),
            'timestamp': report.get('timestamp'),
        }

    @staticmethod
    def check_tls_expiry() -> dict[str, Any]:
        """Check TLS certificate expiry. Returns dict with days and status."""
        mail_hostname = os.environ.get('MAIL_HOSTNAME', '')
        domain = primary_domain()
        cert_paths = []
        if mail_hostname:
            cert_paths.append(
                os.path.join(_LETSENCRYPT_DIR, 'live', mail_hostname, 'fullchain.pem')
            )
        if domain and domain != mail_hostname:
            cert_paths.append(os.path.join(_LETSENCRYPT_DIR, 'live', domain, 'fullchain.pem'))

        if not cert_paths:
            return {
                'days': None,
                'status': 'err',
                'error': 'No TLS certificate found — domain not configured',
            }

        if not shutil.which('openssl'):
            logger.error('openssl not found on PATH; cannot check TLS expiry')
            return {'days': None, 'status': 'err', 'error': 'openssl not available'}

        for cert_path in cert_paths:
            if not os.path.isfile(cert_path):
                continue
            try:
                result = subprocess.run(
                    ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    continue
                date_str = result.stdout.strip().split('=', 1)[1]
                end_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=UTC)
                days = (end_date - datetime.now(UTC)).days
                return {
                    'days': days,
                    'status': 'ok' if days > 30 else ('warn' if days > 7 else 'err'),
                    'expiry': end_date.isoformat(),
                }
            except Exception:
                logger.exception('Failed to check TLS certificate expiry')
                continue

        return {'days': None, 'status': 'err', 'error': 'No TLS certificate found'}

    @staticmethod
    def check_dns(domain: str) -> dict[str, Any]:
        """Validate DNS records for a domain. Returns per-record status.

        Uses the in-process resolver (dnspython), so it works in the api container
        which has no ``dig``, and it checks that records point at *this* server.
        """
        from backend.apps.domains.services.verification import DomainVerificationService

        return DomainVerificationService.check(domain).as_dict()

    @staticmethod
    def get_full_health() -> dict[str, Any]:
        """Aggregate health check — database, redis, TLS, disk."""
        health: dict[str, Any] = {
            'timestamp': datetime.now(UTC).isoformat(),
            'checks': {},
        }

        # Database
        try:
            from django.db import connections

            with connections['default'].cursor() as c:
                c.execute('SELECT 1')
            health['checks']['database'] = {'status': 'ok'}
        except Exception as e:
            health['checks']['database'] = {'status': 'err', 'detail': str(e)}

        # Redis
        try:
            from django.core.cache import cache as _cache

            _cache.set('__health_check', 1, timeout=5)
            if _cache.get('__health_check') == 1:
                health['checks']['redis'] = {'status': 'ok'}
            else:
                health['checks']['redis'] = {'status': 'err', 'detail': 'Readback failed'}
        except Exception as e:
            health['checks']['redis'] = {'status': 'err', 'detail': str(e)}

        # TLS
        tls = MonitoringService.check_tls_expiry()
        health['checks']['tls'] = {
            'status': tls.get('status', 'err'),
            'days': tls.get('days'),
        }

        # Disk
        try:
            import shutil

            disk_paths = os.environ.get('DISK_CHECK_PATHS', f'{_MAIL_VHOSTS_DIR},{_APP_DIR},/')
            for path in disk_paths.split(','):
                path = path.strip()
                if os.path.exists(path):
                    usage = shutil.disk_usage(path)
                    pct = (usage.used / usage.total) * 100
                    health['checks']['disk'] = {
                        'status': 'ok' if pct < 80 else ('warn' if pct < 95 else 'err'),
                        'pct': round(pct, 1),
                        'free_gb': round(usage.free / (1024**3), 1),
                    }
                    break
        except Exception as e:
            health['checks']['disk'] = {'status': 'err', 'detail': str(e)}

        # Overall
        statuses = [v.get('status') for v in health['checks'].values()]
        if all(s == 'ok' for s in statuses):
            health['status'] = 'ok'
        elif 'err' in statuses:
            health['status'] = 'err'
        else:
            health['status'] = 'warn'

        return health
