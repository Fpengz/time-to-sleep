# Time-to-Sleep Web UI Design

## Goal

Add a production-quality browser dashboard for the existing FastAPI usage backend.
The dashboard must make provider health and quota usage understandable at a glance,
while keeping the backend as the only runtime and preserving the existing API
contract.

## Product direction

The interface is a dark instrument panel by default only when the operating system
prefers dark mode. It remains calm and information-dense rather than decorative:
status, freshness, and next action are visually distinct. The light theme uses warm
paper-tinted neutrals; the dark theme uses ink-tinted neutrals with a restrained
lime accent for healthy live data. Typography uses a distinctive display face for
the product title and a readable sans-serif for operational data.

## Architecture

Use a static HTML/CSS/JavaScript frontend served by FastAPI at `/`. This keeps the
project on the existing Python/uv workflow and avoids bringing back the removed
Node/Vite runtime. Static assets live under `src/time_to_sleep/static/` and are
mounted by `src/time_to_sleep/api.py`.

The frontend calls only the existing versioned endpoints:

- `GET /v1/usage` for normalized usage snapshots.
- `GET /v1/usage?force_refresh=true` for a manual refresh.
- `GET /v1/accounts` for configured account readiness.
- `POST /v1/accounts/{account_id}/login/start` for Codex setup.
- `GET /v1/accounts/{account_id}/login/{attempt_id}` for login polling.
- `POST /v1/accounts/{account_id}/login/{attempt_id}/cancel` for cancellation.

The root route serves the application shell. `/docs`, `/health`, and all existing
`/v1/*` routes remain unchanged.

## Layout and states

The page contains:

1. A compact header with the Time-to-Sleep mark, a last-updated label, refresh
   action, and theme toggle.
2. A summary band showing the number of live, cached/stale, and unavailable
   accounts, plus the next reset when one is available.
3. A responsive provider list. Each account row shows provider/account identity,
   status badge, source and observation age, one or more usage windows with percent,
   reset timing, and the diagnostic message when applicable.
4. A focused setup action for an unavailable Codex account. The action presents
   browser and device-code choices, then shows the returned URL/code and polls the
   attempt until success, failure, cancellation, or expiry.

Live, cached, stale, and unavailable states use both text and color so they remain
understandable without color perception. Loading, request failure, empty, and
partial-success states are explicit and do not block healthy sibling accounts.

## Theme behavior

On first load, the page follows `prefers-color-scheme`. The toggle cycles between
light and dark as an explicit user override, stored in `localStorage`. A stored
override wins over system preference on later visits. The theme is applied before
the page becomes visible to prevent a light/dark flash, and the toggle exposes its
current state with an accessible label.

## Interaction and accessibility

Refresh is available from the header and announces its progress. Buttons have
visible focus states and text labels/tooltips. The dashboard remains usable with
keyboard navigation and at narrow widths. Motion is limited to row entrance and
refresh feedback, with transitions disabled under `prefers-reduced-motion`.

## Verification

Add tests for root HTML serving and static assets. Use a browser smoke test to
verify initial rendering, system-theme detection, explicit theme persistence,
manual refresh, account status rendering, and Codex setup error/success states.
Run the existing Python test suite and Ruff/Ty checks after the UI is added.
