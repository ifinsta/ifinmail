"""Frontend contract tests: the redesign's production guarantees, enforced in CI.

These tests read the templates, stylesheets and settings as files, so they need no
browser. Behavioural checks (layout, overflow, accessibility) are described in
.agents/skills/ifinmail-design-audit/SKILL.md.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import resolve

from backend.config.branding import DEFAULT_PRIMARY, DEFAULT_SECONDARY

ROOT = Path(__file__).resolve().parents[4]
FRONTEND = ROOT / 'frontend'
TEMPLATES = sorted((FRONTEND / 'templates').rglob('*.html'))
CSS = FRONTEND / 'static' / 'css'
# Mail clients strip classes and <style>, so email bodies legitimately keep inline styles.
EMAIL_TEMPLATES = {'password_reset_email.html', 'email_verify.html'}


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _token(name: str) -> str:
    match = re.search(rf'--ifinmail-{name}:\s*(#[0-9A-Fa-f]{{6}})', _read(CSS / 'ifinmail-variables.css'))
    assert match, f'token --ifinmail-{name} missing'
    return match.group(1).lower()


@pytest.mark.parametrize('path', TEMPLATES, ids=lambda p: str(p.relative_to(FRONTEND / 'templates')))
def test_template_compiles(path: Path) -> None:
    name = str(path.relative_to(FRONTEND / 'templates')).replace('\\', '/')
    try:
        get_template(name)
    except TemplateDoesNotExist:
        pytest.fail(f'{name} cannot be loaded')


@pytest.mark.parametrize('path', TEMPLATES, ids=lambda p: str(p.relative_to(FRONTEND / 'templates')))
def test_template_has_no_inline_script_style_block_or_handler(path: Path) -> None:
    """CSP forbids inline scripts, and styles live in the stylesheets."""
    if path.name in EMAIL_TEMPLATES:
        pytest.skip('email templates must inline their styles')
    source = _read(path)
    assert not re.search(r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")[^>]*>', source), 'inline <script>'
    assert not re.search(r'\son(click|change|submit|load|input|keydown)\s*=', source, re.I), 'inline event handler'
    assert '<style' not in source, 'inline <style> block (move it to ifinmail-redesign.css)'


def test_base_template_loads_redesign_layer_last_and_registers_it_for_offline_use() -> None:
    base = _read(FRONTEND / 'templates' / 'base.html')
    links = re.findall(r"versioned_css 'css/(ifinmail-[a-z]+\.css)'", base)
    assert links[-1] == 'ifinmail-redesign.css'
    worker = _read(FRONTEND / 'static' / 'js' / 'service-worker.js')
    for name in links:
        assert f'/static/css/{name}' in worker, f'{name} missing from the service worker precache'


def test_production_csp_forbids_inline_scripts() -> None:
    settings = _read(ROOT / 'backend' / 'config' / 'settings' / 'production.py')
    block = re.search(r'CSP_SCRIPT_SRC\s*=\s*\((.*?)\n\)', settings, re.S)
    assert block, 'CSP_SCRIPT_SRC not found'
    directives = '\n'.join(line.split('#')[0] for line in block.group(1).splitlines())
    assert 'unsafe-inline' not in directives


def test_brand_defaults_match_design_tokens() -> None:
    assert DEFAULT_PRIMARY == _token('color-primary')
    assert DEFAULT_SECONDARY == _token('color-brand')


def test_manifest_matches_brand_and_points_at_a_real_route() -> None:
    manifest = json.loads(_read(FRONTEND / 'static' / 'manifest.json'))
    assert manifest['theme_color'].lower() == _token('color-brand')
    assert resolve(manifest['start_url']).url_name == 'dashboard'


def test_root_font_size_keeps_rem_tokens_at_documented_sizes() -> None:
    """A 14px root would shrink every rem token (body 13px would render at 11px)."""
    layout = _read(CSS / 'ifinmail-layout.css')
    root = re.search(r'(?m)^html\s*\{([^}]*)\}', layout)
    assert root and re.search(r'font-size:\s*100%', root.group(1))


def test_phone_rules_use_wordmark_and_continuous_surface() -> None:
    css = _read(CSS / 'ifinmail-redesign.css')
    phone = css[css.index('@media (max-width: 767px)') :]
    assert '.ifinmail-wordmark' in phone
    assert '.ifinmail-landing-nav__logo' in phone
    assert 'border-radius: 0' in phone and 'border: 0' in phone


def test_standalone_pages_expose_a_main_landmark() -> None:
    for name in ('admin/login.html', 'admin/password_reset_form.html', 'registration/step_profile.html'):
        assert '<main' in _read(FRONTEND / 'templates' / name), f'{name} needs a <main> landmark'


@pytest.mark.skipif(not (shutil.which('bash') and shutil.which('grep')), reason='needs bash and grep')
def test_design_audit_script_reports_no_findings() -> None:
    script = ROOT / '.agents' / 'skills' / 'ifinmail-design-audit' / 'scripts' / 'audit.sh'
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, cwd=ROOT, check=False)
    assert result.returncode == 0, result.stdout[-2000:]
