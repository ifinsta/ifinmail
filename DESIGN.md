# ifinmail Design Guide

Compact, quiet, blue-means-interactive. Derived from the ifinsta compact system and applied to the admin console, sign-in and registration, the setup wizard, public and legal pages, error pages and system emails.

This file is the short form. The full guide, tokens, patterns and per-template board map live in `.agents/skills/ifinmail-design-system/`. Reference designs (all 50 templates, desktop and 390 px): https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE

## Principles

1. Blue (`--ifinmail-color-primary`) is interactive only. One primary action per screen.
2. Borders lift, shadows float. White cards with a 1 px border on the `surface-1` page; shadows only for menus and dialogs.
3. Compact: 36 px controls (40 on forms, 44 on phone), 4 px grid, 16 px gap and panel padding, 32 px page gutter.
4. Status is a word on a tint. Never colour alone.
5. Data is mono (numbers, hosts, DNS values, timestamps) and numeric columns are right-aligned.
6. One next action in empty, error and success states.
7. Reuse patterns; do not invent a second version of one that exists.

## Small screens (up to 767 px)

- One continuous white surface, edge to edge, no bordered cards; hairline dividers between sections.
- Brand is the wordmark "ifinmail". No logo icon on small screens.
- Pages shorter than the viewport are vertically centred; long pages start at the top.
- Sidebar becomes a drawer; header is hamburger, wordmark, actions.
- 44 px touch targets.

## Settings hub

All configuration lives under **Settings** (`/accounts/settings/`), grouped as Workspace, Access, Personalization and System. The catalogue is one typed list in `backend/apps/accounts/services/settings_catalogue.py`; the left list, the hub overview and the sidebar highlight are all generated from it.

- A page that edits or shows settings extends `admin/settings_base.html`, defines `settings_content`, and sets `active_section` to its catalogue key.
- A new page without its own view is added to the catalogue with `url_kwargs={'slug': ...}` and either a builder in `views/settings_hub.py` (read-only values from `EffectiveConfig`, secrets shown only as "Configured") or its own template.
- Below 1200 px the category list is replaced by the hub overview and a back link; on phones the overview is one borderless list.
- Read-only pages state that values come from the deployment environment and name the variable beside each value.

## Themes

Light (default), Dark, Auto and High contrast. `ifinmail-theme-init.js` runs in `<head>` and sets `html[data-theme]` (the choice, stored in `localStorage`) and `html[data-scheme]` (what renders: light, dark or contrast). Theme blocks live at the end of `ifinmail-variables.css` and change token values only.

- Never write a literal colour in component CSS. A new literal-colour token in `:root` must also be defined in the `dark` and `contrast` blocks (a test enforces this).
- Text on a primary fill uses `--ifinmail-on-primary`, never white.
- Text contrast must hold in all three schemes; check with axe in each (`localStorage.setItem('ifinmail-theme', 'dark')`).

## Where things live

| What | Where |
| --- | --- |
| Tokens | `frontend/static/css/ifinmail-variables.css` (`--ifinmail-*`) |
| Redesign styles (canonical, loaded last) | `frontend/static/css/ifinmail-redesign.css` |
| Legacy styles (being retired) | `ifinmail-layout.css`, `ifinmail-components.css`, `ifinmail-admin.css` |
| Template list and board map | `docs/html_templates.md` |
| Skills for agents | `.agents/skills/` |

## Compliance

Run `.agents/skills/ifinmail-design-audit/scripts/audit.sh` and the checklist in `.agents/skills/ifinmail-design-audit/SKILL.md` before finishing any UI change.
