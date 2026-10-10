# ifinmail tokens

Source of truth for implementation: `frontend/static/css/ifinmail-variables.css` (prefix `--ifinmail-`). The redesign uses the ifinsta token set. Values that differ from what ships today are marked **change**; update the variable, never the template.

## Colour

| Role | Redesign value | CSS variable | Today | Note |
| --- | --- | --- | --- | --- |
| Primary | #1a56db | `--ifinmail-color-primary` | #1A56DB | same |
| Primary hover | #3b6fe8 on light fills, #1648c0 on solid buttons | `--ifinmail-color-primary-hover` | #1648c0 | keep #1648c0 for solid buttons |
| Primary tint | #e8f0fe | `--ifinmail-color-primary-tint` | #EFF6FF | **change** (active nav, info, selected) |
| Primary subtle | #f0f4ff | `--ifinmail-color-primary-subtle` | #F0F4FF | row hover, active step row |
| Brand navy | #0f2b5b | `--ifinmail-color-brand` | #0F2B5B | wordmark, public headlines, marks |
| Text | #111827 | `--ifinmail-color-text-primary` | #111827 | |
| Text secondary | #374151 | `--ifinmail-color-text-secondary` | #374151 | |
| Text muted | #656d7a | `--ifinmail-color-text-muted` | #6B7280 | **change** (4.7:1 on surface-2) |
| Border | #d1d5db | `--ifinmail-color-border` | #D1D5DB | inputs, cards |
| Divider | #e5e7eb | `--ifinmail-color-border-light` | #E5E7EB | inside cards |
| Page | #f9fafb | `--ifinmail-color-surface-1` | #F9FAFB | |
| Subtle surface | #f3f4f6 | `--ifinmail-color-surface-2` | #F3F4F6 | idle pill, code block, table header alt |
| Card | #ffffff | `--ifinmail-surface-container-lowest` | #ffffff | |
| Success | #059669 fill, #047857 text | `--ifinmail-color-success` | #059669 | add `--ifinmail-color-success-text: #047857` |
| Warning | #d97706 fill, #b45309 text | `--ifinmail-color-warning` | #D97706 | add `--ifinmail-color-warning-text: #b45309` |
| Danger | #dc2626 fill, #b91c1c text | `--ifinmail-color-danger` | #DC2626 | add `--ifinmail-color-danger-text: #b91c1c` |
| Tints | #d1fae5 / #fef3c7 / #fee2e2 | `--ifinmail-color-*-tint` | same | |

Status pill text uses the darker `*-text` values so it clears 4.5:1 on its tint. Fills (dots, buttons) use the base colour.

## Type

| Style | Size / weight | Variable | Today |
| --- | --- | --- | --- |
| Page title | 20 / 600 | `--ifinmail-font-size-page-title` (add, 1.25rem) | h1 18px **change** |
| Panel title | 15 / 600 | `--ifinmail-font-size-h2` | 15px |
| Body | 13-14 / 400 | `--ifinmail-font-size-body` | 13px |
| Label | 13 / 500 | `--ifinmail-font-size-body` + medium | 12px **change** |
| Caption | 12 / 400 | `--ifinmail-font-size-body-small` | 12px |
| Overline | 11 / 600, +0.08em, caps | `--ifinmail-font-size-overline` | 11px |
| Mono data | 12-13 / 500 | `--ifinmail-font-mono` | |
| Public hero | 30-46 / 700, -0.02em | `--ifinmail-font-size-4xl` and up | |

Minimum readable size is 12 px. Nothing below that except the 11 px overline.

## Space, shape, elevation

- Spacing: 4 px grid. Common stops 4, 8, 12, 16, 20, 24, 32, 48, 64 (`--ifinmail-space-*`).
- Radius: controls and cards 8 (`--ifinmail-radius-lg`; **change** buttons and inputs from 6 to 8), pills 5 (add `--ifinmail-radius-badge`), dialogs and auth cards 12, avatars full.
- Control heights: 30 sm (inline), 36 default, 40 forms on auth and wizard, 44 landing CTAs.
- Elevation: only floating layers. Menus `0 4px 12px rgba(0,0,0,.10), 0 2px 4px rgba(0,0,0,.06)`. Dialogs `0 8px 24px rgba(0,0,0,.12), 0 4px 8px rgba(0,0,0,.08)`. Restore these as `--ifinmail-shadow-2` and `--ifinmail-shadow-3`; keep `-1` and `-4` at `none` for cards and toasts.
- Focus ring: 2 px `--ifinmail-color-primary` outline, 2 px offset, on every control.

## Layout

Sidebar 224 / rail 64, header 56, footer 32, content max 1280, page gutter 32 (16 on phones), section gap 16, hero padding 64-72.

## Themes

Light is the shipped theme. Dark and high-contrast follow the ifinsta token pairs (primary #3b82f6 / #1e3a8a, surface-1 #111827 / #ffffff, on-primary #111827 / #ffffff). Never write a literal colour that would not survive a theme swap; always go through a variable.
