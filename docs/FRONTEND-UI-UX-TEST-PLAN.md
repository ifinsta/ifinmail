# Frontend UI/UX and End-to-End Test Plan

## Purpose

This plan gives a frontend specialist a complete testing path for the ifinmail proposal/admin experience. It covers compactness, UI/UX quality, HTML templates, CSS components, JavaScript behavior, and frontend-to-backend action flows.

The goal is to prove that the interface is ready for production use by an operations user: dense enough to work quickly, clear enough to avoid mistakes, accessible, responsive, and correctly wired to backend views and services.

## Visual Direction

The UI should borrow principles from Gmail and Windows 11 without copying either product: calm density, clean lists, clear command surfaces, soft copy, predictable navigation, and quiet status feedback. The experience should feel modern and professional, but never loud or decorative.

Acceptance checks:

- Use subtle borders, tonal surface changes, and spacing to create hierarchy.
- Do not use decorative box shadows for cards, panels, tables, modals, toasts, buttons, or hover states.
- Keep action language soft and direct: "Save changes", "Refresh", "Export", "Reset", "Sign out".
- Make the primary action obvious, but do not over-style it or compete with secondary actions.
- Prefer compact list/table density inspired by mail clients: users should scan status, sender/domain/user, timestamp, and action quickly.
- Prefer Windows 11-like restraint for controls: rounded but not pill-heavy, calm surfaces, visible focus outlines, and minimal animation.
- Success, warning, and error states should speak softly: clear label, calm color, no visual alarm unless the issue is critical.

## Quality Gates

A build is not ready to ship until all of these are true:

- Every authenticated page renders without template errors at desktop, tablet, and mobile widths.
- Each list or table screen shows useful operational density: target 8-12 rows or list items per viewport where data exists.
- No page has horizontal scrolling at 390px, 768px, 1024px, 1280px, or 1440px widths unless the scroll is deliberately scoped to a data table.
- All primary, secondary, destructive, and disabled states are visually distinct and match `DESIGN.md`.
- Light and dark mode pass WCAG AA contrast for normal text and controls.
- Keyboard navigation can reach every interactive control in a logical order.
- CSRF-protected POST actions work with valid tokens and fail without them.
- Disabled high-risk actions remain unavailable from the UI and return forbidden responses if invoked directly.
- Every user action has end-to-end delivery: trigger, pending state, backend response, persisted or returned result, and visible success/error feedback.
- Manual browser QA and Django integration tests pass for smoke, responsive, accessibility, and backend action-flow coverage.

## Test Environment

Use a production-like local or CI environment:

- Django settings: `backend.config.settings.testing` or the closest CI-safe settings module.
- Static files available through Django test server or the same server path used in deployment.
- Seeded staff/admin account with known credentials.
- Seeded domains, DNS records, log rows, spam provider rows, users, sessions, and setup states.
- Email/DNS/system integrations mocked at the service boundary so tests verify calls and UI behavior without changing the host machine.
- Fresh browser profiles or private windows available for authenticated, unauthenticated, and first-run setup flows.

Recommended browser and viewport matrix:

- Chrome or Chromium desktop: `1440x900`, `1280x800`, `1024x768`.
- Chrome or Chromium mobile simulation: `390x844`.
- Firefox desktop: `1280x800`.
- Safari or WebKit-equivalent smoke pass where available.
- Light mode and dark mode.
- Reduced motion mode for interaction checks.

## Product Surfaces in Scope

### Base and Error Templates

Test these templates directly or through the routes that render them:

- `frontend/templates/base.html`
- `frontend/templates/error_base.html`
- `frontend/templates/400.html`
- `frontend/templates/403.html`
- `frontend/templates/404.html`
- `frontend/templates/500.html`
- `frontend/templates/502.html`
- `frontend/templates/503.html`
- `frontend/templates/504.html`

Checks:

- Header, sidebar, skip links, main content, metadata, manifest, CSS, and JS are loaded once.
- Error pages present a clear status, recovery action, and compact layout.
- Error pages do not expose stack traces, settings, secrets, usernames, or host paths.
- Error pages work without authenticated navigation dependencies.

### Shared Includes

Test these through every page that consumes them:

- `frontend/templates/includes/header.html`
- `frontend/templates/includes/sidebar.html`
- `frontend/templates/includes/admin_table.html`
- `frontend/templates/includes/setup_table.html`

Checks:

- Header height remains compact and stable.
- Sidebar active state matches the current route.
- Sidebar collapse/expand works with mouse and keyboard.
- Table headers remain readable and aligned with cells.
- Empty, loading, populated, and overflow table states are handled.
- Mobile navigation does not hide the active page or trap focus.

### Admin Templates

Test each admin template as a first-class screen:

- `frontend/templates/admin/login.html`
- `frontend/templates/admin/dashboard.html`
- `frontend/templates/admin/dns_config.html`
- `frontend/templates/admin/spam_filtering.html`
- `frontend/templates/admin/user_management.html`
- `frontend/templates/admin/branding_identity.html`
- `frontend/templates/admin/logs.html`

Checks:

- Page title and first meaningful content appear quickly.
- Primary action hierarchy is obvious, with only one primary action per screen where possible.
- Dense metrics and tables remain scannable.
- Dangerous actions are red or otherwise clearly destructive.
- Forms provide labels, validation messages, and preserved user input after errors.
- No hard-coded fake data is presented as live production state.

### Admin Partials

Test each partial through populated and empty parent pages:

- `frontend/templates/admin/partials/admin_row.html`
- `frontend/templates/admin/partials/dns_row.html`
- `frontend/templates/admin/partials/log_row.html`
- `frontend/templates/admin/partials/provider_row.html`
- `frontend/templates/admin/partials/queue_row.html`

Checks:

- Row height is compact and consistent.
- Long domains, email addresses, IP addresses, usernames, provider names, and log messages wrap or truncate professionally.
- Status badges include text, not only color.
- Action buttons have accessible names and stable hit targets.
- Row hover/focus state does not cause layout shift.

### Setup Wizard Templates

Test first-run and resumed setup paths:

- `frontend/templates/setup/welcome.html`
- `frontend/templates/setup/dns_provider.html`
- `frontend/templates/setup/dns_auto.html`
- `frontend/templates/setup/dns_manual.html`
- `frontend/templates/setup/create_account.html`
- `frontend/templates/setup/done.html`

Checks:

- Step progression is clear and compact.
- Back, continue, manual setup, and automatic setup actions preserve state.
- Manual DNS instructions are readable on mobile without horizontal page scroll.
- Account creation errors are inline and specific.
- Final state gives an obvious route into the admin dashboard.

## Static Assets in Scope

### CSS Files

Test every component defined in:

- `frontend/static/css/ifinmail-variables.css`
- `frontend/static/css/ifinmail-reset.css`
- `frontend/static/css/ifinmail-utilities.css`
- `frontend/static/css/ifinmail-layout.css`
- `frontend/static/css/ifinmail-components.css`

CSS checks:

- Tokens match the semantic roles in `DESIGN.md`: blue interactive, red destructive, amber caution, green success.
- Dark mode variables exist and preserve contrast.
- Reset rules do not remove visible focus states.
- Utility classes do not conflict with component classes.
- Layout CSS supports the expected 64px top navigation and 240px sidebar with collapsed state.
- Fixed-format elements have stable dimensions and do not resize when labels, icons, badges, or loading text change.
- Buttons, links, forms, tables, cards, badges, status dots, progress bars, code blocks, empty states, and navigation elements all have hover, focus, active, disabled, and error states.
- Decorative `box-shadow` is absent. Focus visibility must use outlines or another accessible non-shadow treatment.
- Panels and cards remain legible through borders, muted backgrounds, and spacing instead of elevation effects.

### JavaScript Files

Test browser behavior in:

- `frontend/static/js/ifinmail-api.js`
- `frontend/static/js/ifinmail-sidebar.js`
- `frontend/static/js/service-worker.js`

JavaScript checks:

- API helper sends CSRF tokens on unsafe methods.
- API helper handles JSON and non-JSON error responses without crashing the page.
- Sidebar state persists as intended and does not break mobile navigation.
- Service worker caches only safe static assets.
- Service worker does not cache authenticated pages, dashboard routes, logs, DNS views, mail routes, setup routes, or `/`.
- Browser console is free of runtime errors during normal navigation and form submission.

## Component Checklist

Test these UI components across all pages where they appear:

- App shell: top header, sidebar, main region, footer or page bottom.
- Navigation: active links, collapsed labels, mobile menu, account/logout affordances.
- Tables: admin table, setup table, DNS rows, provider rows, queue rows, log rows.
- Cards and panels: stat panels, table panels, settings sections, setup sections.
- Forms: login, DNS provider configuration, domain registration, spam sensitivity, provider add form, branding save/reset, account creation.
- Inputs: text, password, email, number, file upload, select, checkbox, toggle/switch, hidden CSRF fields.
- Buttons: primary, secondary, ghost, destructive, icon-only, disabled, loading.
- Status UI: badges, dots, alerts, validation errors, success messages, warning messages.
- Log/code UI: log rows, monospace blocks, DNS record values, export/download links.
- Empty states: no logs, no users, no providers, no DNS records, no queue items.
- Loading states: rescan, DNS refresh, export, live logs, setup advance, save/reset.
- Responsive states: sidebar collapse, stacked forms, table overflow, compact metric grids.

## Compactness and UX Acceptance Criteria

Apply these checks to every screen:

- Default body copy is 13px or 14px, with no text below 12px.
- A single component uses no more than two type sizes unless there is a clear design-system reason.
- Cards and panels avoid oversized padding; dense operational pages should not feel like marketing pages.
- Tables and lists show 8-12 useful rows at `1440x900` when test data exists.
- Repeated controls are aligned in predictable columns.
- Advanced actions are placed in context or secondary positions instead of competing with primary workflows.
- Color is semantic and never the only indication of state.
- Long content is handled: domains, DNS TXT values, IPv6 addresses, usernames, emails, file names, and log messages.
- Focus rings are visible on all interactive elements.
- Copy is direct and consistent: "Save changes", "Reset", "Export", "Refresh", "Sign in", "Sign out".
- Empty states explain what happened and offer the next useful action when appropriate.

## End-to-End Action Delivery Standard

Every frontend action must be tested as a complete delivery loop:

- The control is visible only when the user has permission to use it.
- The control has a clear accessible name and uses the correct visual priority.
- The action sends the expected method, URL, payload, and CSRF token where required.
- The UI enters a pending state for slow actions without changing layout unexpectedly.
- The backend view calls the appropriate service layer and returns a clear response.
- The UI displays the final state: success, validation error, permission error, or system failure.
- Persisted changes remain visible after page refresh.
- Failed actions leave the previous state intact and explain the next step calmly.
- Downloads and exports return correct filename, content type, and content.
- Destructive actions require appropriate danger styling and must not be hidden behind ambiguous copy.

## Frontend-to-Backend Action Flows

### Authentication and Access Control

Routes:

- `GET /accounts/login/`
- `POST /accounts/login/`
- `POST or GET /accounts/logout/`
- `GET /accounts/`
- `GET /accounts/dashboard/`

Tests:

- Unauthenticated users are redirected to login for protected pages.
- Valid credentials establish a session and redirect to the dashboard.
- Invalid credentials show an inline error without losing the username field unnecessarily.
- Logout clears the session and prevents back-button access to protected content.
- Legacy `/admin/` and `/admin/<path>` redirects land on the account/admin area, not Django admin.
- Django admin remains mounted only at `/manage-panel/`.

### Dashboard

Routes:

- `GET /accounts/dashboard/`
- `POST /accounts/dashboard/rescan/`
- `POST /accounts/dashboard/log-purge/`
- `POST /accounts/dashboard/shell/`
- `POST /accounts/dashboard/reboot/`

Tests:

- Dashboard metrics, queue rows, service status, and recent activity render from backend context.
- Rescan action sends CSRF token, shows loading feedback, and displays result or error state.
- Log purge action requires explicit destructive treatment and confirms the backend response.
- Shell action is not visible in production UI and direct requests return `403`.
- Reboot/restart action is not visible in production UI and direct requests return `403`.
- No shell command output, host internals, or privileged controls are exposed in the DOM.

### DNS Configuration

Routes:

- `GET /dns/`
- `POST /dns/configure/`
- `GET /dns/status/`
- `POST /dns/register/`
- `GET /dns/export/`
- `POST /dns/toggle-proxy/`
- `POST /dns/toggle-relay/`
- `POST /dns/set-hop-count/`

Tests:

- DNS page renders configured domain state, required records, provider settings, and validation states.
- Configure provider form validates provider name, credentials, and missing fields.
- Register domain validates domain format and shows clear success or failure.
- Status refresh updates visible DNS state without layout shift.
- Export downloads a file with correct content type and sensible filename.
- Proxy and relay toggles update labels and states consistently.
- Hop count input validates numeric limits and invalid values return clear errors.
- Long TXT, DKIM, SPF, DMARC, MX, IPv4, and IPv6 records remain inspectable.

### Spam Filtering

Routes:

- `GET /accounts/spam-filtering/`
- `POST /accounts/spam-filtering/set-sensitivity/`
- `POST /accounts/spam-filtering/add-provider/`

Tests:

- Sensitivity control renders current value and available options.
- Sensitivity save updates state and handles invalid values.
- Provider add form validates required fields and duplicate providers.
- Provider rows show status, name, type, and actions in compact form.
- Empty provider state does not claim fake integrations are active.

### User Management

Routes:

- `GET /accounts/users/`
- `GET /accounts/users/export/`
- `POST /accounts/users/kill-sessions/`

Tests:

- User table renders email, role/status, activity, session count, and available actions.
- Export returns a downloadable file and does not break navigation.
- Kill sessions is destructive, CSRF-protected, and shows result state.
- Long email addresses and names do not break the table.
- Empty user state is clear and does not present placeholder users as real.

### Branding and Identity

Routes:

- `GET /accounts/branding/`
- `POST /accounts/branding/save/`
- `POST /accounts/branding/reset/`

Tests:

- Branding form renders current brand values.
- Save validates text, colors, and uploaded assets where present.
- Reset uses destructive or caution styling and restores default preview values.
- File upload controls are accessible and validate type/size.
- Preview updates do not obscure form controls or overflow mobile layout.

### Logs

Routes:

- `GET /accounts/logs/`
- `GET /accounts/logs/live/`
- `GET /accounts/logs/full/`
- `GET /accounts/logs/export/`

Tests:

- Logs page renders recent rows with severity, timestamp, source, and message.
- Live logs endpoint updates the UI without duplicating rows endlessly.
- Full history loads more rows without freezing the browser.
- Export returns a downloadable file.
- Long log messages wrap inside the log area and do not create full-page horizontal scroll.
- Severity colors are paired with labels.

### Setup Wizard

Routes:

- `GET /accounts/setup/`
- `GET /accounts/setup/<step>/`
- `POST /accounts/setup/advance/`

Tests:

- Welcome step starts the wizard from a clean first-run state.
- DNS provider step supports automatic and manual paths.
- DNS auto step validates provider configuration and reports connection failures.
- DNS manual step presents copyable records and does not overflow on mobile.
- Create account step validates username/email/password and creates the first account only when valid.
- Done step links into the dashboard and does not expose setup controls after completion.
- Reopening completed setup redirects or shows completed state according to product rules.

### Mail Autoconfiguration

Routes:

- `GET /.well-known/autoconfig/mail/config-v1.1.xml`
- `GET /mail/config-v1.1.xml`
- `GET /autodiscover/autodiscover.xml`

Tests:

- Mozilla autoconfig XML returns valid XML and correct content type.
- Outlook autodiscover XML returns valid XML and correct content type.
- Domain and protocol values are correct for the seeded environment.
- Autoconfig routes do not require an admin browser session.

### Health and Error Recovery

Routes:

- `GET /health/`
- `GET /health/full/`
- `GET /health/dns/`
- `GET /health/deliverability/`
- Synthetic `400`, `403`, `404`, `500`, `502`, `503`, `504` render paths.

Tests:

- Health routes return expected status codes and machine-readable responses.
- UI handles backend failures with clear messages.
- Error templates render compactly and do not leak sensitive data.

## Test Execution Strategy

This project uses server-rendered Django templates, shared CSS, and small JavaScript helpers. Keep the test plan aligned to that architecture: verify rendered HTML, CSS behavior, and Django view responses directly.

Use three complementary passes:

- Manual browser QA for layout, compactness, visual hierarchy, keyboard navigation, and dark mode.
- Django integration tests for routes, redirects, permissions, CSRF behavior, response status codes, rendered templates, and backend side effects.
- Browser DevTools checks for console errors, network requests, cache behavior, responsive layout, and performance.

Suggested Django integration coverage:

```python
def test_dashboard_requires_login(client):
    response = client.get("/accounts/dashboard/")
    assert response.status_code in {302, 303}
    assert "/accounts/login/" in response["Location"]


def test_disabled_dashboard_shell_forbidden(admin_client):
    response = admin_client.post("/accounts/dashboard/shell/")
    assert response.status_code == 403


def test_disabled_dashboard_reboot_forbidden(admin_client):
    response = admin_client.post("/accounts/dashboard/reboot/")
    assert response.status_code == 403


def test_dns_page_uses_expected_template(admin_client):
    response = admin_client.get("/dns/")
    assert response.status_code == 200
    assert any(t.name == "admin/dns_config.html" for t in response.templates)
```

Manual browser checks should use seeded data and inspect actual rendered pages, not static mockups. For each page, confirm:

- Correct template content appears.
- No full-page horizontal overflow at target viewports.
- Tables and lists retain compact row density.
- Form actions submit to the expected backend endpoint.
- Successful and failed submissions produce clear UI feedback.
- Browser console has no runtime errors.
- Network tab shows expected status codes, redirects, content types, and cache headers.

## Manual QA Pass

Run this manual pass before signing off:

1. Start from a fresh browser profile.
2. Visit a protected page and confirm redirect to login.
3. Sign in.
4. Visit Dashboard, DNS, Spam Filtering, Users, Branding, and Logs.
5. Resize each page to `1440x900`, `1024x768`, `768x1024`, and `390x844`.
6. Switch system appearance to dark mode and repeat the visual scan.
7. Tab through each page and confirm focus visibility and logical order.
8. Submit every form once with valid input and once with invalid input.
9. Trigger export/download actions and inspect filenames and content types.
10. Open DevTools console and confirm no runtime errors.
11. Disable JavaScript and confirm basic navigation and server-rendered forms fail gracefully where JS is required.
12. Throttle network to Slow 3G and confirm loading states are understandable.

## Negative and Security-Focused UI Tests

Include these in manual browser QA or Django integration tests:

- POST without CSRF to unsafe endpoints returns `403`.
- Unauthenticated unsafe requests redirect or fail according to Django policy.
- Low-privilege users cannot access admin-only pages.
- Direct shell and reboot endpoint calls return `403`.
- Invalid DNS domains do not create records.
- Invalid hop count, spam sensitivity, provider credentials, account data, and branding inputs show validation errors.
- Uploaded branding assets reject unsupported file types and oversized files.
- Service worker does not serve stale authenticated pages after logout.
- Browser cache does not retain sensitive dashboard, log, or user-management responses after logout.

## Visual Regression Screenshots

Capture and review screenshots for:

- Login page.
- Dashboard populated state.
- Dashboard empty or degraded backend state.
- DNS configuration with long TXT/DKIM values.
- Spam filtering with providers and empty state.
- User management with long email/name data.
- Branding form with preview.
- Logs with long messages and multiple severities.
- Setup wizard: all six steps.
- Error pages: `403`, `404`, and one `5xx` page.

Screenshots must be captured in:

- Light mode desktop.
- Dark mode desktop.
- Mobile portrait.
- Tablet portrait.

Review for:

- Horizontal scroll.
- Overlapping text.
- Unclear action hierarchy.
- Excess padding.
- Missing focus or hover states.
- Unreadable color contrast.
- Sticky header/sidebar covering content.
- Bad wrapping of DNS records and logs.

## Performance and Resilience

Measure these during browser DevTools or Lighthouse-style runs:

- First meaningful admin page render under 2 seconds locally with seeded data.
- No large layout shift when tables load or actions complete.
- CSS and JS bundles stay small enough for an operations dashboard; investigate any unexpected asset growth.
- Repeated live log polling does not leak DOM nodes or duplicate entries.
- Sidebar toggling does not trigger expensive full-page layout churn.
- Forms remain responsive while backend actions are pending.

## Deliverables

The frontend specialist should produce:

- Manual QA checklist covering smoke, responsive, accessibility, and action-flow tests.
- Django integration tests for route, template, CSRF, permission, and backend action behavior.
- Screenshot archive for the visual regression set.
- Bug report list with route, template, viewport, browser, expected behavior, actual behavior, screenshot, and severity.
- Final readiness summary that explicitly says whether the proposal/admin frontend is production ready.

## Production Readiness Sign-Off Template

Use this summary format after the test pass:

```md
## Frontend Readiness Summary

Status: Ready / Not Ready
Test date:
Build or commit:
Browsers tested:
Viewports tested:
Pages tested:
Critical issues:
High issues:
Accessibility result:
Compactness result:
Backend action-flow result:
Service worker/cache result:
Residual risks:
Recommended release decision:
```
