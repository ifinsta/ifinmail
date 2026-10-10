---
name: ifinmail-template-builder
description: Step-by-step workflow for creating or changing an ifinmail Django template, partial, CSS component or page script so it matches the approved redesign. Use whenever a task touches frontend/templates, frontend/static/css or frontend/static/js, or adds a new screen.
---

# Building ifinmail templates

Pair this with `ifinmail-design-system` (what it should look like) and finish with `ifinmail-design-audit` (prove it does).

## 1. Find the design first

1. Look up the template in `.agents/skills/ifinmail-design-system/references/template-map.md` and open that board in the redesign canvas (https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE).
2. New screen with no board: pick the closest pattern from `references/patterns.md`. Compose from existing patterns; if you genuinely need a new one, design it in the canvas first (reuse the `Icon`, `Pill`, `Btn`, `Field`, `PageHead`, `Sidebar`, `TopBar` components) and add a board plus a row in `template-map.md` and `docs/html_templates.md`.
3. Note every state the board shows (empty, error, loading, success, inactive) and build all of them.

## 2. Pick the layout

| Screen type | Extend | Blank these blocks |
| --- | --- | --- |
| Admin page | `base.html` | none; set `sidebar_wrapper` to `{% include "includes/sidebar.html" %}` and `header` to `{% include "includes/header.html" %}`, pass `active_section` |
| Sign-in, reset, registration | `base.html` with its own `body_layout` | `sidebar_wrapper`, `header`, `footer` via `body_layout` override |
| Setup wizard | `setup/base.html` | standalone layout |
| Error | `error_base.html` | sidebar, header, footer (already blank) |
| Landing, legal | `base.html` | `sidebar_wrapper`, `header`, `footer` |
| Email | none | inline styles only (mail clients strip classes) |
| nginx fallback | none | one self-contained `<style>`, no JS, no web fonts |

Available blocks in `base.html`: `title`, `head`, `body_class`, `body_layout`, `sidebar_wrapper`, `header`, `content`, `footer`, `sidebar_script`, `scripts`, `service_worker`.

## 3. Write the markup

- Start with `{% load i18n %}` (and `{% load static %}` when you reference static files). Every visible string is `{% trans %}` or `{% blocktrans trimmed %}`. Variables inside blocktrans use `with`.
- Admin page skeleton: `section.ifinmail-admin-content > div.ifinmail-admin-page`, then a `.ifinmail-page-header` (title, subtitle, `.ifinmail-page-actions`), then panels. Keep the `<h1>` unique per page.
- Tables go through `includes/admin_table.html` with a `row_template` partial. Add a column by editing the partial, not by copying the table.
- Class names are `ifinmail-<block>` / `ifinmail-<block>__<element>` / `ifinmail-<block>--<modifier>`. Reuse before you add. New CSS goes in the right file: variables (`ifinmail-variables.css`), layout (`-layout.css`), components (`-components.css`), admin-only (`-admin.css`), helpers (`-utilities.css`).
- Style with `var(--ifinmail-*)` only. No hex, no `px` font sizes below 12, no inline `style=` unless a value is computed at render time (progress width, chart bar height).
- Icons are inline SVG with `aria-hidden="true"` and `currentColor`. Icon-only buttons have `aria-label`.
- Forms: `{% csrf_token %}`, a `<label for>` for every control, `autocomplete` and `inputmode` set, helper and error text linked with `aria-describedby`, submit disables and shows a spinner while pending.
- Modals: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trap, Esc to close, return focus to the opener.
- State changes (toasts, validation) use `role="status"` or `role="alert"`.

## 4. Script behaviour

Page scripts live in `frontend/static/js/ifinmail-<page>.js`, are loaded from `{% block scripts %}`, use `data-action` and `data-url` attributes for hooks (never inline `onclick`), and read the CSRF token via `ifinmail-csrf.js`. Respect `prefers-reduced-motion`.

## 5. Architecture contract (from AGENTS.md)

Views never touch models directly: `web.py -> views -> forms -> services -> models`. Template context comes from the view; do not reach into services from a template tag. Types and enums are imported from `types/`.

## 6. Small screens

Follow "Small screens" in `ifinmail-design-system`: borderless, edge to edge, one white surface, wordmark instead of logo, short pages vertically centred, 44 px targets. Put the rules in the `@media (max-width: 767px)` block of `ifinmail-redesign.css`. Markup needs a `.ifinmail-wordmark` element wherever a logo mark appears.

## 7. Verify

1. Render at 1280, 768 and 360 px wide. Sidebar collapses, toolbars wrap, tables scroll inside their box, nothing overflows the page.
2. Tab through the page: every control reachable, focus ring visible, order matches reading order.
3. Run `.agents/skills/ifinmail-design-audit/scripts/audit.sh <changed files>` and fix findings.
4. Run the app (`USE_SQLITE=1 DJANGO_SETTINGS_MODULE=backend.config.settings.development python manage.py runserver --noreload`, restart after template edits) and load each affected page at 1280 and 390 px. Confirm no horizontal overflow and no console errors. Template names that need DEBUG off (404, 500) render with `DEBUG=False --insecure`.
5. Update `docs/html_templates.md` if you added, removed or renamed a template.
