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
