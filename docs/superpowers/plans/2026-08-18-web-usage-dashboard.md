# Web Usage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a responsive FastAPI-served usage dashboard with system-aware light/dark themes, live account data, refresh controls, and Codex setup actions.

**Architecture:** Keep a single Python runtime. FastAPI serves a static application shell from `src/time_to_sleep/static/`; browser JavaScript calls the existing `/v1` endpoints, renders normalized snapshots, and owns only ephemeral UI state. Theme selection starts from `prefers-color-scheme`, then persists an explicit light/dark override in `localStorage`.

**Tech Stack:** FastAPI `StaticFiles`/`FileResponse`, semantic HTML, modern CSS, browser JavaScript, pytest/TestClient, and Playwright browser smoke tests.

---

### Task 1: Mount the static frontend shell through FastAPI

**Files:**
- Create: `src/time_to_sleep/static/index.html`
- Create: `src/time_to_sleep/static/styles.css`
- Create: `src/time_to_sleep/static/app.js`
- Modify: `src/time_to_sleep/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing root and asset tests**

Add these tests to `tests/test_api.py`:

```python
def test_root_serves_dashboard() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Time-to-Sleep" in response.text
    assert "/static/app.js" in response.text


def test_static_stylesheet_is_served() -> None:
    response = TestClient(app).get("/static/styles.css")

    assert response.status_code == 200
    assert "--bg:" in response.text
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run `uv run pytest tests/test_api.py::test_root_serves_dashboard tests/test_api.py::test_static_stylesheet_is_served -q`.

Expected: both tests fail because `/` and `/static/styles.css` do not exist.

- [ ] **Step 3: Add the static mount and application shell**

In `src/time_to_sleep/api.py`, add:

```python
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
```

Create an HTML shell with a semantic header, live region, summary section, account
list root, setup panel root, and references to `/static/styles.css` and
`/static/app.js`. The shell must include a blocking inline theme bootstrap before
the stylesheet:

```html
<script>
  (() => {
    const saved = localStorage.getItem("time-to-sleep-theme");
    const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.dataset.theme = saved || system;
  })();
</script>
```

Add the initial CSS token declarations for both `[data-theme="light"]` and
`[data-theme="dark"]`, so the asset test can find `--bg:`.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```bash
uv run pytest tests/test_api.py::test_root_serves_dashboard tests/test_api.py::test_static_stylesheet_is_served -q
uv run ruff check src/time_to_sleep/api.py tests/test_api.py
uv run ty check
```

Expected: both tests pass and Python checks remain clean.

- [ ] **Step 5: Commit**

```bash
git add src/time_to_sleep/api.py src/time_to_sleep/static tests/test_api.py
git commit -m "feat: serve dashboard shell from FastAPI"
```

### Task 2: Build the visual system and responsive dashboard layout

**Files:**
- Modify: `src/time_to_sleep/static/styles.css`
- Modify: `src/time_to_sleep/static/index.html`

- [ ] **Step 1: Define the visual tokens and layout regions**

Use a warm paper light palette and ink-tinted dark palette. The stylesheet must
define `--bg`, `--surface`, `--surface-raised`, `--text`, `--muted`, `--line`,
`--accent`, `--positive`, `--warning`, and `--danger` under both theme selectors.
Use a distinctive display font stack for `.brand` and a readable sans-serif stack
for operational data. Use CSS grid for the summary and account rows, with a
single-column mobile layout below `720px`.

- [ ] **Step 2: Add the dashboard markup**

The shell must contain these stable selectors for browser verification:

```html
<button id="theme-toggle" type="button" aria-label="Switch color theme"></button>
<button id="refresh-button" type="button">Refresh usage</button>
<time id="last-updated" datetime="">Waiting for first sync</time>
<p id="live-announcement" class="sr-only" aria-live="polite"></p>
<section id="summary" aria-label="Usage summary"></section>
<section id="account-list" aria-label="Provider usage"></section>
<section id="setup-panel" hidden aria-labelledby="setup-title"></section>
```

Include a loading skeleton and an explicit empty/error slot that JavaScript can
toggle without replacing the whole document.

- [ ] **Step 3: Verify the static page visually**

Start the API with `uv run uvicorn time_to_sleep.api:app --host 127.0.0.1 --port 4141`,
open `http://127.0.0.1:4141/`, and confirm the page has a clear header, generous
left alignment, distinct summary/account hierarchy, visible focus states, and no
horizontal scrolling at desktop and mobile widths. Stop the server after the
inspection.

- [ ] **Step 4: Commit**

```bash
git add src/time_to_sleep/static/index.html src/time_to_sleep/static/styles.css
git commit -m "feat: add responsive dashboard visual system"
```

### Task 3: Implement data rendering, theme toggle, and refresh behavior

**Files:**
- Modify: `src/time_to_sleep/static/app.js`
- Modify: `src/time_to_sleep/static/index.html`

- [ ] **Step 1: Add typed-by-convention client state and API helpers**

Implement these functions in `app.js`:

```javascript
const state = { snapshots: [], accounts: [], loading: false, theme: null };

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

async function loadUsage(forceRefresh = false) {
  const suffix = forceRefresh ? "?force_refresh=true" : "";
  return getJson(`/v1/usage${suffix}`);
}

async function loadAccounts() {
  return getJson("/v1/accounts");
}
```

Render each `UsageSnapshot` with account name, provider label, status text, source,
observation age, every usage window, percent bar width, reset label, and message.
Never use color alone to communicate status. Escape all server strings through
`textContent` or DOM node creation rather than assigning untrusted values to
`innerHTML`.

- [ ] **Step 2: Implement the theme controller**

Use `localStorage` key `time-to-sleep-theme`. If absent, use
`matchMedia("(prefers-color-scheme: dark)")`; clicking `#theme-toggle` writes the
opposite explicit theme and updates `document.documentElement.dataset.theme`.
Update the button label and icon text after every change. Listen for system theme
changes only while no explicit override exists.

- [ ] **Step 3: Implement refresh and state feedback**

On `DOMContentLoaded`, load accounts and usage concurrently, render loading and
partial-failure states, and update `#last-updated` from `generated_at`. Clicking
`#refresh-button` calls `loadUsage(true)`, disables itself while pending, updates
`#live-announcement`, and restores the control in `finally`.

- [ ] **Step 4: Verify behavior with an API-backed browser session**

With the FastAPI server running, verify that the initial page renders four account
records, a manual refresh updates the live region, and the toggle changes the root
`data-theme` attribute without navigating away. Also verify the browser console has
no uncaught errors.

- [ ] **Step 5: Commit**

```bash
git add src/time_to_sleep/static/index.html src/time_to_sleep/static/app.js
git commit -m "feat: connect dashboard to usage API"
```

### Task 4: Add Codex setup interaction and resilient UI states

**Files:**
- Modify: `src/time_to_sleep/static/app.js`
- Modify: `src/time_to_sleep/static/styles.css`
- Modify: `src/time_to_sleep/static/index.html`

- [ ] **Step 1: Render setup actions for unavailable Codex accounts**

For an unavailable Codex snapshot, show a `Set up account` button in that account
row. Clicking it opens the setup panel, which contains a method select with
`browser` and `device_code`, a start button, and a cancel button. Do not show
credentials or local paths in the panel.

- [ ] **Step 2: Implement the login lifecycle**

Use the existing endpoints with this flow:

```javascript
const challenge = await getJson(`/v1/accounts/${accountId}/login/start`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ method }),
});
renderChallenge(challenge);
pollLogin(accountId, challenge.attempt_id);
```

Poll every two seconds until the attempt is no longer `pending`, stop polling on
success/failure/cancel/expiry, announce the result, and reload usage/accounts on
success. Render an authorization link with `target="_blank"` and `rel="noreferrer"`
when `auth_url` exists, plus verification URL and user code when supplied.

- [ ] **Step 3: Add explicit diagnostic and loading states**

Use labels and explanatory copy for live, cached, stale, unavailable, timeout,
expired, rate-limited, and not-configured states. Keep healthy sibling rows visible
when one request fails. Respect `prefers-reduced-motion` by disabling entry
transitions under the matching media query.

- [ ] **Step 4: Verify setup states with mocked browser responses**

Use a browser test route interception to verify a fake unavailable secondary Codex
row exposes setup, a fake browser challenge renders its URL/code, and a fake
completed attempt removes the panel after refreshing usage. Verify that cancelling
the panel stops polling.

- [ ] **Step 5: Commit**

```bash
git add src/time_to_sleep/static/index.html src/time_to_sleep/static/app.js src/time_to_sleep/static/styles.css
git commit -m "feat: add Codex setup flow to dashboard"
```

### Task 5: Add browser smoke coverage and operational handoff

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/browser_dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Add Playwright to the development group**

Add `playwright>=1.50,<2` to `[dependency-groups].dev`, run `uv sync`, and install
the local Chromium browser with `uv run playwright install chromium` when the
browser is not already installed.

- [ ] **Step 2: Create the browser smoke script**

The script must launch Chromium headlessly, navigate to `http://127.0.0.1:4141/`,
wait for `networkidle`, assert `#summary` and `#account-list` are visible, click
`#theme-toggle`, assert the root theme changes, click `#refresh-button`, and fail
if console errors or uncaught page exceptions occur. It must close the browser in
`finally`.

- [ ] **Step 3: Document the web UI commands**

Update `README.md` with `uv run uvicorn time_to_sleep.api:app --reload`, the root
dashboard URL, `/docs`, theme behavior, and the browser smoke command:

```bash
uv run python tests/browser_dashboard.py
```

- [ ] **Step 4: Run the complete verification matrix**

Run:

```bash
uv sync
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run uvicorn time_to_sleep.api:app --host 127.0.0.1 --port 4141
uv run python tests/browser_dashboard.py
```

Expected: all Python tests pass, formatting/lint/type checks pass, and the browser
script exits successfully against the running API.

- [ ] **Step 5: Commit the handoff**

```bash
git add pyproject.toml README.md tests/browser_dashboard.py uv.lock
git commit -m "test: verify web dashboard in browser"
```
