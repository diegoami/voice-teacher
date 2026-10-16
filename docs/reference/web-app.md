# Installable web app shell

T15 establishes `apps/web`, the mobile-first React/TypeScript client. The owner
confirmed an installable Android/desktop web app for the first release. The UI
uses native labelled inputs, selects, radio groups and buttons, with visible
keyboard focus and touch-sized controls; no component library is required.
[Recording/playback](voice-client.md) is implemented by T16; full pause/continue
and restart flows belong to T17.

## Build and serve

Use Node 22.12+ (validated with Node 24) and the committed npm lockfile:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
npm --prefix apps/web test -- --run
node apps/web/node_modules/@playwright/test/cli.js install chromium
npm --prefix apps/web run test:e2e -- catalogue
```

Serve `apps/web/dist` from the Python API's existing `assets` setting (or T10's
`python -m voice_teacher --assets /absolute/path/apps/web/dist`). API routes take
precedence. Set the API origin to the exact public origin. Phone installation
requires stable HTTPS (T28); desktop localhost is suitable for development.

For local UI development, `npm --prefix apps/web run dev` proxies `/api` to
127.0.0.1:8000. Configure the server origin to `http://127.0.0.1:5173` and open
that exact browser origin. Production uses same-origin static assets and API.
No browser-to-provider calls or frontend environment credentials are needed.

The manifest supplies standalone display, root start URL/scope, theme/background
and code-drawn 192/512 PNG icons with safe maskable padding. Chromium installability
is checked through `Page.getInstallabilityErrors` against the production build.
No service worker or private offline response cache is installed. Practice needs
its server connection; installability does not imply offline speech. Browser
installation UI and actual phone behavior remain T19 checks. This follows the
[MDN installability guidance](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable),
[Vite build guide](https://vite.dev/guide/) and
[Playwright server guidance](https://playwright.dev/docs/test-webserver).

## Pairing and server selection

An operator creates a short-lived, learner-bound pairing code using the
[session API](session-api.md). The browser exchanges it through `/api/v1/pair`;
the response now includes the authenticated `learner_id` as well as its existing
client grant. `/api/v1/identity` returns only that learner ID and requires the
paired bearer. It rejects operator tokens, anonymous and revoked clients. No
personal profile is included.

The UI displays the verified identity before exposing its catalogue. It stores
the client bearer and expiry in origin-scoped local storage, revalidates identity
on page load and clears the bearer on 401/disconnect. Treat the browser profile
as private: another person with access to it can use its pairing. Disconnect
removes local access; server-side revocation is the operator action. Pairing codes
are cleared after exchange and are not stored. No operator/provider credentials
are requested by the UI or bundled. Built assets contain no deployment secrets.

A different server address opens that origin's own app. The browser never forwards
the current bearer, pairing code or session selections to it. Server addresses
must be clean HTTPS origins (HTTP only for localhost/loopback), without embedded
credentials, paths or token queries. The server keeps the API's same-origin guard;
no permissive CORS configuration is added. Server selection and the server's
private progress destination are independent settings.

## Catalogue and saved sessions

Sources, courses and lessons come from authenticated API responses; there are no
hard-coded lesson paths. Every mode is presented with its actual availability.
An authored but unsupported mode explains that its server planner is not enabled;
a mode absent from the lesson explains the content limitation. The Start button
is disabled until the complete source/course/lesson/mode is available. Repetition and guided conversation are available through their server planners;
free conversation remains a later task.

The browser remembers selection and session links by verified learner ID and
browser origin. Selection changes do not modify an existing session. A start
receives a fresh client-generated session ID; its original request and source
revision metadata are saved locally before POST. If creation saved state but delivery
failed, opening/recovering the link reads the session by that ID. A recovery GET
404 permits retrying the same start body/ID; other errors do not create a second
session. The authoritative content snapshot and access checks stay on the server.
This is a local list of known links, not the complete history (T18).

Catalogue and server failures show a retry action. Response payloads are not
rendered as error text. Per-effect cancellation prevents an older catalogue
response replacing newer source selections. Requests omit cookies, refuse
redirects, use bearer headers and `cache: no-store`, and have a bounded timeout.
Only public HTML/JS/CSS/manifest/icons are built; private sessions/transcripts/audio
are fetched after authentication and are never part of a service-worker cache.

## Verification boundary

Browser catalogue tests use two synthetic fake server catalogues with overlapping
course/lesson IDs. They exercise pairing, both sources, mode selection, unsupported
modes, remembered selection, original-session recovery after source change,
failed delivery/start, server errors, revocation, learner separation, foreign-server
navigation, keyboard selection, native mobile taps on mode/start controls, responsive layout,
control sizing and installability.
They run the production build for desktop and emulated Android Chromium.
Playwright is pinned to 1.63.0 for reproducibility. Native host rendering was
unreliable in both Chromium 153 and 156: even a minimal native animation-frame
probe stalled intermittently, including under a virtual display. The isolated official Playwright container
ran all 14 desktop/Android-sized scenarios successfully after correcting an
exact-label test selector to the control’s accessible combobox role. Preserve normal
actionability checks; do not use forced clicks or substitute animation timers.
These are
not real Android microphone, headset, locked-screen or network measurements.
Python API tests independently check identity ownership, revocation and role gates.
The Web app GitHub workflow runs the same build/unit/browser commands on a fresh
Ubuntu runner, with read-only repository permissions, no deployment credentials,
immutable action pins and retained synthetic screenshots/failure traces.
