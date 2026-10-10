---
name: ifinmail-design-audit
description: Check a template, stylesheet or screenshot against the ifinmail redesign before finishing or when reviewing a change. Includes an automated scan script and a manual checklist. Use after any UI change, in code review, or when asked whether something "matches the design".
---

# ifinmail design audit

## Automated scan

```bash
.agents/skills/ifinmail-design-audit/scripts/audit.sh                 # whole frontend
.agents/skills/ifinmail-design-audit/scripts/audit.sh path/to/file    # specific files or folders
```

It reports file:line for each hit and exits 1 when anything is found. It flags:

| Check | Why |
| --- | --- |
| Literal hex or `rgb()` colours in templates and component CSS | Colours must come from `--ifinmail-*` tokens (themes break otherwise). `ifinmail-variables.css`, the static error pages and email templates are exempt |
| Inline `style=` in templates | Use classes. Exempt: computed widths and heights, email templates, static error pages |
| `box-shadow` outside menus, dialogs and the landing preview | Cards use borders |
| `font-size` below 12 px (except the 11 px overline) | Readability |
| Emoji or pictographs in markup | Use inline SVG |
| `<div>` or `<span>` with `onclick`, `role="button"` | Use `<button>` / `<a>` |
| `<img>` without `alt` | Accessibility |
| `<input>` without an `id` that a `<label for>` can target | Every control needs a label |
| `{% trans %}`-less visible text in `<h1>`..`<h3>`, `<button>`, `<th>` | i18n |
| Gradients | No gradient washes |
| `text-transform: uppercase` outside overlines and pills | Table headers are sentence case |
| `ifinmail-btn--primary` used more than once in a template | One primary action per screen (check by hand when it is in different states) |

Treat a hit as a question, not a verdict: fix it, or explain in the change why it is a legitimate exception.

## Manual checklist

Compare the result with the matching board (see `ifinmail-design-system/references/template-map.md`).

**Look**
- [ ] Page ground `surface-1`, cards white with a 1 px border, no shadows on cards
- [ ] One primary button per view; secondary actions are white or link-style
- [ ] Pills use word + tint; numbers, hosts, timestamps are mono and numeric columns right-aligned
- [ ] Spacing sits on the 4 px grid; gutter 32, panel padding 16, gap 16
- [ ] Controls 36 px (40 on auth and wizard), radius 8, pills radius 5, dialogs 12
- [ ] Type matches the scale (title 20/600, panel 15/600, body 13-14, caption 12, overline 11 caps)

**States**
- [ ] Empty, loading, error, success and disabled states exist and read as one next action
- [ ] Destructive actions are confirmed in a dialog; the confirm button names the action
- [ ] Validation errors sit under the field with `danger-text`, linked by `aria-describedby`

**Accessibility**
- [ ] Every control reachable by keyboard, 2 px focus ring visible, logical order
- [ ] Text contrast 4.5:1 (3:1 for 24 px+); status never relies on colour alone
- [ ] Icon-only buttons have `aria-label`; decorative SVG has `aria-hidden`; dialogs trap focus
- [ ] Respects `prefers-reduced-motion`; nothing flashes

**Responsive**
- [ ] 1280, 768 and 360 px: sidebar collapses, header wraps, tables scroll in their own box, no horizontal page scroll
- [ ] Touch targets 44 px on phone-first public and auth pages

**Content and structure**
- [ ] All copy in `{% trans %}`; sentence case; no lorem ipsum or invented stats
- [ ] Only `--ifinmail-*` tokens; new tokens added to `ifinmail-variables.css` first
- [ ] Layering follows `web.py -> views -> forms -> services -> models`; no model access from templates
- [ ] `docs/html_templates.md` and the template map updated if a template was added, removed or renamed

## Reporting

List findings as `file:line - rule - fix`, most severe first (accessibility and broken states, then token and pattern violations, then polish). Say plainly which checks you could not run.
