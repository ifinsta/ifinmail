---
name: ifinmail-design-system
description: The ifinmail visual language (compact, quiet, blue-means-interactive, derived from the ifinsta system). Use before designing, redesigning or reviewing ANY ifinmail UI - Django templates under frontend/templates, CSS under frontend/static/css, static error pages, system emails, the Android web shell or a design artifact - so new work lines up with the approved redesign.
---

# ifinmail design system

One system covers the admin console, sign-in and registration, the setup wizard, public and legal pages, error pages and system emails. It is a compact enterprise look: dense but calm, borders instead of shadows, one blue for everything interactive.

**Approved reference (read it before drawing anything new):**
- Redesign canvas, all 50 templates: https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE (private; ask the owner for access)
- Source inspiration (ifinsta compact system): https://claude.ai/artifact/SLYdVZjTPp1W1S69kfsrbf
- Template -> board map: `references/template-map.md`
- Token values and how they map to `frontend/static/css/ifinmail-variables.css`: `references/tokens.md`
- Component recipes and page patterns: `references/patterns.md`

`AGENTS.md` points at a `DESIGN.md`. If one exists, it wins on any conflict; otherwise this skill is the design guide.

## The seven rules

1. **Blue means interactive.** `primary` (#1a56db) is for the one primary action per screen, links, focus rings and the active nav item. Never use it for decoration or status.
2. **Borders lift, shadows float.** Cards and tables are white with a 1 px `border` (#d1d5db) on the `surface-1` (#f9fafb) page. Shadows exist only for things that float above the page: menus, dialogs and the landing-page product window.
3. **Compact by default.** Controls are 36 px tall (40 px on sign-in, registration and wizard forms, 44 px for landing CTAs). Page gutter 32, panel padding 16, gap 16, 4 px base grid.
4. **Status is a word on a tint.** Pills are 20 px, radius 5, 12/600, text always accompanied by a label (PASS, Deferred, Offline). Never colour alone, never a bare dot without text nearby.
5. **Data is mono.** Numbers, hosts, IPs, DNS values, timestamps, log lines, selectors: JetBrains Mono. Numeric columns are right-aligned.
6. **One next action.** Empty, error and success states say what happened and offer a single button or link. A page is never blanked while loading: show a thin bar and soft placeholders.
7. **Same words, same shape.** Reuse the patterns in `references/patterns.md` (PageHead, stat strip, panel, table, form card, stepper, pill, banner, dialog, empty state). Do not invent a second version of a pattern that exists.

## Core values (quick reference)

| Area | Value |
| --- | --- |
| Font | Inter 400/500/600/700; JetBrains Mono 400/500/600 |
| Page title | 20 / 600 (public pages: 30-46 / 700, navy) |
| Panel title | 15 / 600 |
| Body | 13-14 / 400, line-height 1.45-1.55 |
| Label / nav / tab | 13 / 500 |
| Caption / helper | 12 / 400, `text-muted` |
| Overline | 11 / 600, uppercase, tracking 0.08em |
| Radius | 8 cards, inputs, buttons; 5 pills; 12 dialogs and auth cards; full avatars |
| Colours | primary #1a56db, brand navy #0f2b5b, text #111827 / #374151 / #656d7a, border #d1d5db, divider #e5e7eb, tint #e8f0fe |
| Status text on tint | ok #047857 on #d1fae5, warn #b45309 on #fef3c7, danger #b91c1c on #fee2e2, info #1a56db on #e8f0fe, idle #374151 on #f3f4f6 |
| Layout | sidebar 224 (rail 64), header 56, content max 1280, footer 32 |
| Motion | 100-250 ms, standard easing, `prefers-reduced-motion` respected |

## Hard rules for implementation

- Colours, spacing, radii and type come from `--ifinmail-*` variables. No new hex values in templates or component CSS. If a value is missing, add a token to `ifinmail-variables.css` first.
- No inline `style=` in templates except for genuinely dynamic values (a progress width, a chart bar height). Everything else is a class.
- Icons are inline stroke SVG (stroke 2, round caps, `currentColor`, `aria-hidden="true"`). Never emoji or icon fonts, never raster icons.
- Every interactive element is a real `<a>`, `<button>`, `<input>`, `<select>` with a visible label or `aria-label`. Focus ring is the 2 px primary ring on every control.
- Text contrast 4.5:1 minimum (3:1 at 24 px and up). `text-muted` is #656d7a, not #6b7280, so it holds on `surface-2`.
- All copy goes through `{% trans %}` / `{% blocktrans %}`.
- Pages work at 360 px wide: sidebar collapses behind the header toggle, toolbars wrap, wide tables scroll inside their own box.
- Dark and high-contrast themes: tokens only, never literal colours, so a theme swap works.

## Never

Gradient washes, glass, left-border accent cards, emoji, decorative illustrations, stock photography, uppercase table headers, zebra striping, drop shadows on cards, centered body copy longer than two lines, more than one primary button in a view, red used for anything but errors and destructive actions.

## When you are done

Run `.agents/skills/ifinmail-design-audit/scripts/audit.sh` and walk the checklist in `.agents/skills/ifinmail-design-audit/SKILL.md`.
