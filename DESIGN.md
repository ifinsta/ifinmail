# ifinmail Design Guide

Compact, quiet, blue-means-interactive. Derived from the ifinsta compact system and applied to the admin console, sign-in and registration, the setup wizard, public and legal pages, error pages and system emails.

This file is the short form. The full guide, tokens, patterns and per-template board map live in `.agents/skills/ifinmail-design-system/`. Reference designs (all 50 templates, desktop and 390 px): https://claude.ai/artifact/D9asdXKM7QCbXmDFgkjCCE

## Principles

1. Blue (`--ifinmail-color-primary`) is interactive only. One primary action per screen.
2. Borders lift, shadows float. White cards with a 1 px border on the `surface-1` page; shadows only for menus and dialogs.
3. Compact: 36 px controls (40 on forms, 44 on phone), 32 px nav items, 48 px header, 208 px sidebar that minimizes to a 52 px rail (so does the Settings list), 4 px grid, 12 px section gap, 16 px panel padding, 24 px page gutter.
4. Status is a word on a tint. Never colour alone.
5. Data is mono (numbers, hosts, DNS values, timestamps) and numeric columns are right-aligned.
6. One next action in empty, error and success states.
7. Reuse patterns; do not invent a second version of one that exists.

## Small screens (up to 767 px)

- One continuous white surface, edge to edge, no bordered cards; hairline dividers between sections.
- Brand is the wordmark "ifinmail". No logo icon on small screens.
- On sign-in, registration and error pages the header block (wordmark, title, subtitle, step counter) is centred as one unit; labels, fields and buttons fill the width below it. Do not centre the title and left-align the wordmark, or the reverse.
- Public pages are session-aware: use `user.is_authenticated` and `can_use_console` (context processor) to swap "Sign in" / "Get started" for the account row (`site/_account.html`). Never show a signed-in person a sign-in button.
- Every explanatory public page (features, pricing, security, about, contact, docs, download, changelog, terms, privacy) puts its heading and its content in the same centred column: give both wraps `ifinmail-site-wrap--page` (`--site-column`, 56rem). Inside it a title or label column sits beside the text, as a version does in the changelog. The step from heading to content is one tight space (`space-5`); do not add banner padding. The landing page keeps its wide hero.
- Full-height rules always pair `100vh` with `100dvh` (the second wins where supported). `100vh` alone is the viewport with the address bar hidden, so a short page scrolls by the height of the bar on a phone. A test enforces the pair.
- Pages shorter than the viewport are vertically centred; long pages start at the top. Sign-in, registration, setup and error pages are exactly one viewport tall (`100dvh`): the card is only as tall as its content and is centred together with the link under it, so a short page never scrolls and a long one scrolls naturally. Never give both the page and the card `min-height: 100dvh`.
- Panels run edge to edge and bring their own padding, so text placed directly in `.ifinmail-admin-page` (a note, a help line) takes a 16 px side margin from the phone rules; do not rely on the page for a gutter.
- An element that is also `.ifinmail-site-wrap` must not use a `padding: x 0` shorthand (it removes the gutter); use `padding-top` / `padding-bottom`. A test enforces this.
- The public header switches to the **Menu** button below 880 px, not 768 px: its links need about 860 px.
- Sidebar becomes a drawer; header is hamburger, wordmark, actions.
- 44 px touch targets.

## Logo

An open envelope whose flap is a roof: your mail, on your own server. White glyph on the primary-blue rounded tile, set beside the wordmark **ifin**mail ("ifin" Inter 700 in the brand colour, "mail" Inter 400 in the primary colour, tracking −2%).

| Use | File (`frontend/static/icons/`) |
| --- | --- |
| App tile, in-page mark | `mark.svg` (inline `includes/brand_house.html` in pages, so it follows theme and primary colour) |
| Favicon, 16–48 px | `favicon.ico`, `favicon.svg` (heavier stroke so the flap survives at 16 px) |
| Installed app | `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (80 % safe zone), `apple-touch-icon.png` |
| One colour, any ground | `mark-glyph.svg` (`currentColor`) |
| Wordmark / lockup | `wordmark-light|dark.svg`, `lockup-light|dark.svg` (letters outlined, no font needed); `lockup-email.png` for mail clients |

Rules:

1. The mark and wordmark belong to the unrenamed product. `brand.uses_default_mark` is true only when no logo is uploaded **and** the name is still "ifinmail"; a renamed brand without a logo shows its name as text, never the house. An uploaded logo always wins.
2. Never recolour, outline, stretch or add effects. On a coloured ground use `mark-glyph.svg`; the tile is always the primary colour and the glyph always `--ifinmail-on-primary`.
3. Clear space around the lockup: half the tile height. Minimum: 16 px mark, 80 px lockup. Below 24 px use the heavier `favicon.svg`.
4. In HTML the name is live text (`includes/brand_name.html`), not an image, so it scales, translates and passes contrast in every theme.
5. Small screens show the wordmark only (see above); the rail and favicon carry the mark.
6. Emails use `lockup-email.png` (a PNG, 2× of 222×56): most mail clients drop SVG.

## Avatars and photos

The avatar is a circle: the person's photo (`includes/avatar.html`, `ifinmail-avatar--photo`, cover-fit) or, without one, their initial on the primary tint. Photos are square JPEGs made by the server (`PhotoService`: 256 px for the account page and contacts apps, 96 px for lists and the header); never link the uploaded original, and never render a photo that is not served through `accounts:photo` (it is behind the sign-in and carries a content-hash URL). The upload control is `admin/partials/account_photo.html` with `ifinmail-photo.js`: choose, drag, zoom, then Save; without JavaScript the server centres the square. Images are read as `data:` URLs because `blob:` is not in the Content-Security-Policy.

## Settings hub

All configuration lives under **Settings** (`/accounts/settings/`), grouped as Workspace, Access, Personalization and System. The catalogue is one typed list in `backend/apps/accounts/services/settings_catalogue.py`; the left list, the hub overview and the sidebar highlight are all generated from it.

- A page that edits or shows settings extends `admin/settings_base.html`, defines `settings_content`, and sets `active_section` to its catalogue key.
- A new page without its own view is added to the catalogue with `url_kwargs={'slug': ...}` and either a builder in `views/settings_hub.py` (read-only values from `EffectiveConfig`, secrets shown only as "Configured") or its own template.
- Below 1200 px the category list is replaced by the hub overview and a back link; on phones the overview is one borderless list.
- Read-only pages state that values come from the deployment environment and name the variable beside each value.

## Themes

Smooth (default), Oceanic, Light, Dark, Auto and High contrast. `ifinmail-theme-init.js` runs in `<head>` and sets `html[data-theme]` (the choice, stored in `localStorage`; until someone chooses, the server default from Settings → Appearance, passed as `data-default` on the script tag, and otherwise Smooth) and `html[data-scheme]` (what renders: smooth, oceanic, light, dark or contrast). Theme blocks live at the end of `ifinmail-variables.css` and change token values only.

**Smooth** is the default look: light only (it never follows the operating system into a dark scheme), soft edges instead of hard ones (a pale hairline and one soft shadow on cards; 10 / 14 / 18 px radii; pill badges), quiet surfaces, no gradients, glow or decorative motion. It changes tokens (colours of borders and surfaces, radii, shadows, motion; never the brand or primary colour) and the few components that need more in `ifinmail-smooth.css`, which is loaded last and where every rule starts with `html[data-scheme="smooth"]`. A new page needs nothing special: use tokens and it is smooth. Do not hard-code a radius or a border colour; if a component draws a square box in Smooth, give it a token radius and `--ifinmail-color-border-light`.

**Oceanic** is Smooth's shapes (the same radii, shadows and `ifinmail-smooth.css` rules, which are scoped to `html:is([data-scheme="smooth"], [data-scheme="oceanic"])`) in a light sea-blue palette: deep navy text, a teal-blue accent (`#0C6A8A`), sea-glass surfaces. Light only, never follows the operating system. Unlike Smooth it sets the accent itself, so it replaces a custom brand colour (as Dark does). Status colours (success, warning, danger) are not changed. `test_oceanic_theme.py` measures every text/background pair; change a token there and the test says whether it still clears 4.5:1.

- Never write a literal colour in component CSS. A new literal-colour token in `:root` must also be defined in the `dark` and `contrast` blocks (a test enforces this).
- Text on a primary fill uses `--ifinmail-on-primary`, never white.
- Text contrast must hold in every scheme (smooth, oceanic, dark and contrast); check with axe in each (`localStorage.setItem('ifinmail-theme', 'dark')`).

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
