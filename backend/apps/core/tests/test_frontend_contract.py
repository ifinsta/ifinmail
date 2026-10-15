"""Frontend contract tests: the redesign's production guarantees, enforced in CI.

These tests read the templates, stylesheets and settings as files, so they need no
browser. Behavioural checks (layout, overflow, accessibility) are described in
.agents/skills/ifinmail-design-audit/SKILL.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import resolve, reverse

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
    css = _read(CSS / 'ifinmail-variables.css')
    match = re.search(rf'--ifinmail-{name}:\s*(#[0-9A-Fa-f]{{6}})', css)
    assert match, f'token --ifinmail-{name} missing'
    return match.group(1).lower()


@pytest.mark.parametrize(
    'path', TEMPLATES, ids=lambda p: str(p.relative_to(FRONTEND / 'templates'))
)
def test_template_compiles(path: Path) -> None:
    name = str(path.relative_to(FRONTEND / 'templates')).replace('\\', '/')
    try:
        get_template(name)
    except TemplateDoesNotExist:
        pytest.fail(f'{name} cannot be loaded')


@pytest.mark.parametrize(
    'path', TEMPLATES, ids=lambda p: str(p.relative_to(FRONTEND / 'templates'))
)
def test_template_has_no_inline_script_style_block_or_handler(path: Path) -> None:
    """CSP forbids inline scripts, and styles live in the stylesheets."""
    if path.name in EMAIL_TEMPLATES:
        pytest.skip('email templates must inline their styles')
    source = _read(path)
    script_re = r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")[^>]*>'
    handler_re = r'\son(click|change|submit|load|input|keydown)\s*='
    assert not re.search(script_re, source), 'inline <script>'
    assert not re.search(handler_re, source, re.I), 'inline event handler'
    msg = 'inline <style> block (move it to ifinmail-redesign.css)'
    assert '<style' not in source, msg


def test_base_template_loads_redesign_layer_last_and_registers_it_for_offline_use() -> None:
    base = _read(FRONTEND / 'templates' / 'base.html')
    links = re.findall(r"versioned_css 'css/(ifinmail-[a-z]+\.css)'", base)
    # The Smooth theme's refinements follow the redesign layer and every page's own sheet.
    assert links[-2:] == ['ifinmail-redesign.css', 'ifinmail-smooth.css']
    worker = _read(FRONTEND / 'static' / 'js' / 'service-worker.js')
    for name in links:
        assert f'/static/css/{name}' in worker, f'{name} missing from the service worker precache'


def test_production_csp_forbids_inline_scripts() -> None:
    settings = _read(ROOT / 'backend' / 'config' / 'settings' / 'production.py')
    block = re.search(r'CSP_SCRIPT_SRC\s*=\s*\((.*?)\n\)', settings, re.S)
    assert block, 'CSP_SCRIPT_SRC not found'
    directives = '\n'.join(line.split('#')[0] for line in block.group(1).splitlines())
    assert 'unsafe-inline' not in directives


def test_production_csp_is_enforced_by_default() -> None:
    """Report-only never protects anyone. The switch exists for emergencies, not as the default."""
    settings = _read(ROOT / 'backend' / 'config' / 'settings' / 'production.py')
    assert re.search(r"CSP_REPORT_ONLY\s*=\s*os\.environ\.get\('CSP_REPORT_ONLY', 'False'\)", settings)
    assert 'CSP_REPORT_URI' in settings, 'violations must still be reported'


def test_brand_defaults_match_design_tokens() -> None:
    assert _token('color-primary') == DEFAULT_PRIMARY
    assert _token('color-brand') == DEFAULT_SECONDARY


def test_manifest_is_branded_and_points_at_a_real_route(client) -> None:
    response = client.get(reverse('manifest'))
    assert response.status_code == 200
    manifest = response.json()
    assert manifest['theme_color'].lower() == _token('color-brand')
    assert resolve(manifest['start_url']).url_name == 'dashboard'
    assert manifest['icons'], 'a manifest needs at least one icon'


def test_root_font_size_keeps_rem_tokens_at_documented_sizes() -> None:
    """A 14px root would shrink every rem token (body 13px would render at 11px)."""
    layout = _read(CSS / 'ifinmail-layout.css')
    root = re.search(r'(?m)^html\s*\{([^}]*)\}', layout)
    assert root and re.search(r'font-size:\s*100%', root.group(1))


def test_phone_rules_use_wordmark_and_continuous_surface() -> None:
    css = _read(CSS / 'ifinmail-redesign.css')
    phone = css[css.index('@media (max-width: 767px)') :]
    assert '.ifinmail-wordmark' in phone
    assert 'border-radius: 0' in phone and 'border: 0' in phone


def test_standalone_pages_expose_a_main_landmark() -> None:
    pages = (
        'admin/login.html',
        'admin/password_reset_form.html',
        'registration/step_profile.html',
    )
    for name in pages:
        html = _read(FRONTEND / 'templates' / name)
        assert '<main' in html, f'{name} needs a <main> landmark'


_bash_available = shutil.which('bash') and shutil.which('grep')


@pytest.mark.skipif(not _bash_available, reason='needs bash and grep')
def test_design_audit_script_reports_no_findings() -> None:
    script = ROOT / '.agents' / 'skills' / 'ifinmail-design-audit' / 'scripts'
    script = script / 'audit.sh'
    result = subprocess.run(
        ['bash', str(script)], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert result.returncode == 0, result.stdout[-2000:]


# ── Themes ────────────────────────────────────────────────────────────────────

# Tokens that are deliberately identical in every theme.
_THEME_INDEPENDENT = re.compile(
    r'preview|color-white|color-black|on-dark-muted|on-band|spinner-track-on-dark|bg-grid-size|skeleton-shimmer|bg-grid-image'
)


def _block(css: str, selector: str) -> str:
    start = css.index(selector + ' {')
    return css[start : css.index('\n}', start)]


def _themed_tokens() -> list[str]:
    """Custom properties in :root whose value is a literal colour (or an image literal)."""
    root = _block(_read(CSS / 'ifinmail-variables.css'), ':root')
    names = re.findall(r'(--ifinmail-[\w-]+):\s*(?:#[0-9A-Fa-f]{3,8}|rgba?\(|url\()', root)
    return sorted({n for n in names if not _THEME_INDEPENDENT.search(n)})


@pytest.mark.parametrize('scheme', ['dark', 'contrast'])
def test_every_literal_colour_token_has_a_value_in_each_theme(scheme: str) -> None:
    """A token missing from a theme block silently keeps its light value."""
    block = _block(_read(CSS / 'ifinmail-variables.css'), f'html[data-scheme="{scheme}"]')
    missing = [t for t in _themed_tokens() if f'{t}:' not in block]
    assert not missing, f'{scheme} theme is missing: {missing}'


def test_theme_bootstrap_runs_before_styles_and_is_csp_safe() -> None:
    base = _read(FRONTEND / 'templates' / 'base.html')
    script = base.index('ifinmail-theme-init.js')
    variables = "versioned_css 'css/ifinmail-variables.css'"
    assert script < base.index(variables), 'theme must apply before first paint'
    before = base[script - 40 : script]
    assert '<script src=' in before, 'theme bootstrap must be an external script'
    source = _read(FRONTEND / 'static' / 'js' / 'ifinmail-theme-init.js')
    for choice in ('smooth', 'oceanic', 'light', 'dark', 'auto', 'contrast'):
        assert f"'{choice}'" in source


def test_component_css_does_not_hardcode_white_text_on_primary() -> None:
    """On dark themes the primary is light, so text on it must use --ifinmail-on-primary."""
    css = _read(CSS / 'ifinmail-components.css') + _read(CSS / 'ifinmail-admin.css')
    for rule in re.findall(r'[^{}]+\{[^{}]*\}', css):
        if re.search(r'background(-color)?:\s*var\(--ifinmail-color-primary\)', rule):
            assert 'color: var(--ifinmail-color-white)' not in rule, rule.strip()[:80]


def test_sidebars_can_be_minimized_and_state_applies_before_first_paint() -> None:
    base = _read(FRONTEND / 'templates' / 'base.html')
    init = base.index('ifinmail-layout-init.js')
    styles = base.index("versioned_css 'css/ifinmail-variables.css'")
    assert init < styles, 'rail state must apply before first paint'
    assert '<script src=' in base[init - 40 : init], 'layout bootstrap must be external'
    source = _read(FRONTEND / 'static' / 'js' / 'ifinmail-layout-init.js')
    tokens = ('data-sidebar', 'data-settings-rail', 'ifinmail-sidebar', 'ifinmail-settings-nav')
    for token in (*tokens, 'aria-expanded'):
        assert token in source, token

    # Each toggle announces its state, names what it controls, and carries both labels.
    for template, pane, target in (
        ('includes/sidebar.html', 'sidebar', 'ifinmail-app-sidebar'),
        ('includes/settings_nav.html', 'settings', 'ifinmail-settings-nav'),
    ):
        html = _read(FRONTEND / 'templates' / template)
        assert f'data-collapse-toggle="{pane}"' in html
        assert f'id="{target}"' in html and f'aria-controls="{target}"' in html
        for attribute in ('aria-expanded=', 'data-label-collapse=', 'data-label-expand='):
            assert attribute in html, f'{template} lacks {attribute}'


def test_minimized_rails_keep_tooltips_and_use_the_rail_token() -> None:
    """With labels hidden every link needs a title; rail width comes from the token."""
    for template in ('includes/sidebar.html', 'includes/settings_nav.html'):
        html = _read(FRONTEND / 'templates' / template)
        pattern = r'<a [^>]*class="[^"]*(?:nav-item|settings__link)[^"]*"[^>]*>'
        for anchor in re.findall(pattern, html):
            assert 'title=' in anchor, f'{template}: {anchor[:80]}'
    css = _read(CSS / 'ifinmail-redesign.css')
    assert 'width: var(--ifinmail-sidebar-rail-width)' in css
    assert 'width: var(--ifinmail-sidebar-rail-width)' in css.split('data-settings-rail')[1]
    assert 'width: var(--ifinmail-sidebar-width)' in _read(CSS / 'ifinmail-components.css')


def test_chrome_stays_compact() -> None:
    """Header, sidebar and nav items are deliberately dense; wider looks loose."""
    tokens = _read(CSS / 'ifinmail-variables.css')
    limits = {
        '--ifinmail-header-height': 48,
        '--ifinmail-sidebar-width': 208,
        '--ifinmail-sidebar-rail-width': 52,
        '--ifinmail-sidebar-nav-item-height': 32,
    }
    for name, maximum in limits.items():
        found = re.search(rf'{re.escape(name)}:\s*(\d+)px', tokens)
        assert found and int(found.group(1)) <= maximum, f'{name} must stay <= {maximum}px'
