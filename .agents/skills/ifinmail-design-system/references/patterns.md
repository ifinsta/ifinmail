# Patterns

Each pattern has a live version in the redesign canvas (components row and the page boards). Build with the existing `ifinmail-*` classes from `frontend/static/css/ifinmail-components.css`; add a class there rather than styling in the template.

## Page shell (`base.html`)

`sidebar 208 | header 48 / main (gutter 24, max 1280) / footer 32`. Public, error, setup and sign-in templates blank `sidebar_wrapper`, `header` and `footer`. Sidebar items are 32 px, 13/500, icons 16 px, no padding around the nav (the brand row is 48 px, one line, tagline hidden); active = `primary-tint` fill, `primary` text, 600, `aria-current="page"`. Section labels are overlines. Footer of the sidebar holds server status, Support, More options. Minimize / Maximize: the footer button (and Alt+C) collapses the sidebar to a 52 px icon rail (`html[data-sidebar="collapsed"]`); labels, brand name and status text hide, section labels become hairlines, every item keeps a `title` tooltip. The Settings category list has its own toggle beside its search (`html[data-settings-rail="collapsed"]`, 13rem to 52 px, desktop >= 1200 px only). The Settings list is a full-height column beside the app sidebar (`secondary_nav` block in `base.html`, outside `.ifinmail-app-main`), its search row is header-height and sticky; both sidebars are sticky at 100dvh and scroll on their own (`overscroll-behavior: contain`), independent of the page. State is saved per browser (`ifinmail-sidebar`, `ifinmail-settings-nav`) and applied by `ifinmail-layout-init.js` in `<head>`. The phone drawer ignores both.

## Header (`includes/header.html`)

Hamburger (visible below 960 px), search field 32 px with `/` hint, then notifications, settings, divider, profile button (avatar 28, name 13/600, role as 11 px caps). The profile menu is a 220 px floating card, radius 12, 36 px items, Sign Out in danger text after a divider.

## PageHead

Breadcrumb 12 muted -> title 20/600 -> optional subtitle 13 secondary. Actions on the right in this order: tertiary link, secondary button, primary button. Wraps under the title on phones. No bottom border band inside the content area.

## Stat strip and stat card

Strip: one white bordered card split by 1 px dividers, each cell = 12 muted label, then a dot and a 20-24 mono 600 value. Use when 4-5 figures belong together (dashboard, domain health). Stat card: overline label, 24 mono value, 12/500 trend line coloured by meaning. Use when each figure is its own subject (users, spam).

## Panel

White, 1 px border, radius 8. Header 12-16 padding, 15/600 title, optional overline or link on the right, 1 px divider below. Body padding 16. Tables inside panels are edge to edge.

## Table

Header on `surface-1`, 12/600 muted, no caps. Rows 40 px, 13 px text, 1 px `surface-2` dividers, no zebra. First column carries the name (600, blue only if it is a link). Status = pill. Numbers and technical values = mono; numeric columns right-aligned with a right-aligned header. Wide tables scroll in a `min-width` box. Empty state fills the body (see below).

## Pill

20 px, padding 0 8, radius 5, 12/600. Tones: ok, warning, danger, info, idle (see SKILL.md). Words: PASS, WARN, FAIL for checks; Online/Offline for presence; Active/Deferred for queue; role names for roles.

## Buttons

Primary (blue fill), Secondary (white, border), Link action (blue text, no border), Danger (white, red border and text; solid red only in the confirmation step of a destructive dialog). 36 px, 13/600, radius 8, 14 px side padding. Icon + label gap 8. Disabled = 50% opacity and `disabled`. Loading = spinner inside, width fixed.

## Form field

Label 13/500 above, control 36 or 40 px, radius 8, 1 px border, 12 px side padding, 14 px text. Helper 12 muted below; error 12 `danger-text` replaces the helper and the border turns danger. Required marker is a red asterisk after the label, not in the placeholder. Password fields have an eye toggle with `aria-label`. Technical inputs (domain, IP, host, token) use mono.

## Form card (settings)

Panel with 15/600 title and 12 muted description; fields in a 2-column grid (1 on phones), 14/16 gap; Save (primary) and Reset (secondary) in the PageHead, not at the bottom.

## Stepper

Numbered circles 24 px joined by 1 px lines. Done = solid primary with a check; current = primary-tint fill and primary border; upcoming = white with border. Labels 13, current 600. Wizard (4 steps: Domain, DNS, Account, Done). Registration uses 5 thin bars plus "Step n of 5" because its card is narrow.

## Auth card

Centered on `surface-1` with a faint 32 px navy grid, card max 400, radius 12, padding 32, 44 px brand mark, 22/700 title, 14 secondary subtitle, 40 px fields, one full-width primary button, quiet links underneath. Reset-flow cards add a 36 px tinted icon tile (info, success, danger) above the title. Error and info banners sit between the subtitle and the form.

## Banner

Full width of its container, radius 8, 10-12 padding, 13 px, 16 px icon, tint background with a matching 1 px border and the dark text of the tone. One sentence: what happened, what to do. Danger banners use `role="alert"`.

## Empty, loading, error

Empty: 40 px grey circle with a 20 px icon, 14/600 headline, 13 secondary sentence, one link or button. Loading: keep the layout, show a 6 px progress bar and soft grey blocks. Error: say what failed, that nothing is lost, how to retry.

## Dialog

Max 440-480, radius 12, overlay shadow. Header 16/600 with a 32 px close button, 20 px body with 14 px field gaps, footer right-aligned: Cancel (secondary) then the action (primary). Focus is trapped, Esc closes, first field focused.

## Toggle row

Title 13/600, description 12 muted, switch on the right (40 x 24, `role="switch"`, `aria-checked`). On = primary, off = #9ca3af.

## Code / DNS value

12 px mono on `surface-1` with 1 px divider border, radius 8, padding 10-12, `word-break: break-all`, Copy link top right.

## Timeline / activity

8 px status dot, bold actor, mono timestamp, one sentence below, 1 px dividers. Dot colours: success green, warning amber, danger red.

## Error pages

Centered card (radius 12), kind pill (Client error amber, Server error red), 64/700 code in #c3c9d3, 18/600 title, 13 description, optional "contact support" line for 5xx, primary + secondary buttons. Static nginx pages inline the same tokens in one `<style>` block, no fonts, no JavaScript.

## System email

520 px card on `surface-2`, header with brand mark, 22/700 title, 14/1.6 body, one solid 8-radius blue button (inline styles, table-safe), fallback link in a mono code box, footer line on `surface-1` explaining why they received it. Inline styles are allowed here only because mail clients strip classes.

## Public page

Header 60 px white with brand, anchor links and Sign In / Get Started. Hero: 46/700 navy headline, 16 secondary paragraph, two 44 px CTAs, product preview window (radius 12, overlay shadow). Sections alternate white and `surface-1`, max 1120, 64 px vertical padding, 30/700 section titles. Cards are the standard bordered card. Closing band uses brand navy with a white button. Legal pages: 720 px reading column, 30/700 title, "Last updated" pill, 16/600 section headings separated by 1 px rules.

The public site (`templates/site/`, `ifinmail-site.css`) adds three reusable shapes: **page head** (overline, 30-44/700 navy title, 17 secondary lede, hairline below), **split section** (title and one line on the left, a check list or prose on the right, one hairline between sections; stacks on tablet) and **prose** (68ch column, 20/700 section titles with a top rule, `pre` boxes that scroll). Rules: copy states only what is true (no certifications, plans or uptime figures), nothing is loaded from a third party (fonts are self-hosted), no JavaScript of its own (the phone menu is `<details>`), and every page has one `h1`, a skip link and a `main` landmark.
