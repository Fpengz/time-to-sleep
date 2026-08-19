# Dark Editorial Dashboard Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the existing Time-to-Sleep dashboard into a dark editorial observatory while preserving its API, provider behavior, Codex setup flow, and theme persistence.

**Architecture:** Keep the FastAPI-served static HTML/CSS/JavaScript frontend. Add stable semantic landmarks for the editorial hero, signal strip, provider ledger, and inline setup panel; keep the existing `state` object and endpoint helpers as the client boundary. Improve rendering and feedback in place so the backend contract and login lifecycle remain unchanged.

**Tech Stack:** Semantic HTML, CSS custom properties/grid, browser JavaScript, FastAPI static assets, pytest, and Playwright.

---

## File map

- `src/time_to_sleep/static/index.html` — semantic dashboard shell and stable landmarks.
- `src/time_to_sleep/static/styles.css` — dark/editorial tokens, layout, status treatments, responsive rules, focus states, and reduced-motion behavior.
- `src/time_to_sleep/static/app.js` — hero/signal rendering, refresh feedback, partial-failure messaging, and setup-state presentation.
- `tests/browser_dashboard.py` — browser assertions for the revised hierarchy, responsive layout, state feedback, theme behavior, and setup flow.
- `docs/superpowers/specs/2026-08-19-dark-editorial-dashboard-design.md` — approved design constraints; do not change unless implementation exposes a contradiction.

The backend files under `src/time_to_sleep/api.py`, `src/time_to_sleep/domain.py`, `src/time_to_sleep/services.py`, and `src/time_to_sleep/providers/` are not part of this change.

## Task 1: Lock the revised dashboard contract with failing browser assertions

**Files:**
- Modify: `tests/browser_dashboard.py`

- [ ] **Step 1: Add assertions for the new semantic landmarks**

In `assert_dashboard`, replace the old page-title assertion with checks for the approved editorial structure while retaining the existing account-count, theme-toggle, refresh, and announcement checks:

```python
assert page.locator("#page-title").is_visible()
assert page.locator("#hero-copy").is_visible()
assert page.locator("#next-reset").is_visible()
assert page.locator("#signal-strip").is_visible()
assert page.locator("#provider-ledger").is_visible()
assert page.locator("#account-list .account-card").count() == 4
```

Add an overflow helper near `assert_dashboard`:

```python
def assert_no_horizontal_overflow(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
```

Call it once at the end of the desktop dashboard assertions. Keep the existing theme and refresh checks so this task fails only on the missing revised landmarks, not by removing regression coverage.

- [ ] **Step 2: Run the focused browser check and verify the expected failure**

Start the API in another terminal with `uv run uvicorn time_to_sleep.api:app --host 127.0.0.1 --port 4141`, then run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: the test fails at the first new locator because the current shell does not yet contain `#next-reset`, `#signal-strip`, or `#provider-ledger`.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/browser_dashboard.py
git commit -m "test: define editorial dashboard landmarks"
```

## Task 2: Restructure the static shell around the editorial hierarchy

**Files:**
- Modify: `src/time_to_sleep/static/index.html`

- [ ] **Step 1: Replace the current hero markup with the editorial hero landmarks**

Keep the existing `#page-title` and `#live-announcement` IDs. Replace the current hero contents with this structure so the page has a narrative headline plus an elevated reset datum:

```html
<section class="hero" aria-labelledby="page-title">
  <p class="eyebrow">Nightly provider report <span class="eyebrow-dot" aria-hidden="true"></span></p>
  <div class="hero-row">
    <div class="hero-copy-block">
      <h1 id="page-title">A clear night<br><em>for your quota.</em></h1>
      <p id="hero-copy" class="hero-copy">Waiting for the first provider sync.</p>
    </div>
    <aside class="hero-reset" aria-labelledby="next-reset-label">
      <p id="next-reset-label" class="reset-label">Earliest reset</p>
      <time id="next-reset" datetime="">Waiting for sync</time>
      <p id="next-reset-detail" class="reset-detail">No reset reported</p>
    </aside>
  </div>
  <p class="sync-note">Loopback only<br><span>no credentials leave this machine</span></p>
</section>
```

The `em` element is decorative styling only; JavaScript must continue to render the actual state in `#hero-copy`, `#next-reset`, and `#next-reset-detail`.

- [ ] **Step 2: Turn the summary region into the signal strip and label the ledger**

Change the summary section to keep the `#summary` hook while adding the new testable landmark:

```html
<section id="summary" class="signal-strip" aria-label="Usage summary"></section>
```

Change the accounts section heading and add `#provider-ledger` to the visible section wrapper:

```html
<section id="provider-ledger" class="accounts-section" aria-labelledby="accounts-title">
  <div class="section-heading">
    <div>
      <p class="eyebrow">Provider ledger</p>
      <h2 id="accounts-title">The accounts</h2>
    </div>
    <span class="section-caption">Normalized usage windows</span>
  </div>
  <section id="account-list" class="account-list" aria-label="Provider usage">
    <div class="loading-state" role="status" aria-label="Loading provider usage">
      <span class="loading-line"></span>
      <span class="loading-line short"></span>
      <span class="loading-line shorter"></span>
    </div>
  </section>
</section>
```

Add `aria-live="polite"` to `#setup-panel` so setup status changes are announced without changing focus:

```html
<section id="setup-panel" class="setup-panel" hidden aria-live="polite" aria-labelledby="setup-title"></section>
```

- [ ] **Step 3: Run the browser test and verify it reaches the next missing behavior**

Run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: the new landmarks are found, and the test now either passes the structure assertions or fails on the old `#page-title` text/visual behavior that Task 3 will update.

- [ ] **Step 4: Commit the shell structure**

```bash
git add src/time_to_sleep/static/index.html
git commit -m "feat: add editorial dashboard shell"
```

## Task 3: Render the editorial hero, reset datum, and signal strip

**Files:**
- Modify: `src/time_to_sleep/static/app.js`

- [ ] **Step 1: Add explicit client state for independent account metadata failures**

Extend the existing `state` object with:

```javascript
accountLoadError: null,
```

Keep `snapshots` when a refresh begins. Do not reset it to an empty array; the visible ledger must remain available while new data is pending.

- [ ] **Step 2: Add shared summary helpers**

Add these functions before `renderSummary`:

```javascript
function resetCandidates() {
  return state.snapshots
    .flatMap((snapshot) => (snapshot.windows || []).map((window) => ({ snapshot, window })))
    .filter((candidate) => Number.isFinite(Date.parse(candidate.window.resets_at)))
    .sort((left, right) => Date.parse(left.window.resets_at) - Date.parse(right.window.resets_at));
}

function snapshotCounts() {
  return {
    live: state.snapshots.filter((item) => item.status === "live").length,
    attention: state.snapshots.filter((item) => ["cached", "stale", "rate_limited"].includes(item.status)).length,
    unavailable: state.snapshots.filter((item) => item.status === "unavailable").length,
  };
}
```

- [ ] **Step 3: Add the hero renderer**

Add `renderHero()` and call it from `render()` before `renderSummary()`:

```javascript
function renderHero() {
  const title = select("#page-title");
  const copy = select("#hero-copy");
  const reset = select("#next-reset");
  const detail = select("#next-reset-detail");
  if (!title || !copy || !reset || !detail) return;

  const counts = snapshotCounts();
  const candidate = resetCandidates()[0] || null;
  const total = state.snapshots.length;
  const clear = !total || counts.attention + counts.unavailable === 0;

  title.replaceChildren(
    element("span", { text: clear ? "A clear night" : "A little weather" }),
    element("br"),
    element("em", { text: clear ? "for your quota." : "in the forecast." }),
  );
  if (!total) {
    copy.textContent = state.loading ? "Listening for provider usage…" : state.loadError || "Waiting for the first provider sync.";
  } else if (clear) {
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} reporting live.`;
  } else {
    const needsAttention = counts.attention + counts.unavailable;
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} live; ${needsAttention} need${needsAttention === 1 ? "s" : ""} attention.`;
  }

  if (candidate) {
    const date = new Date(candidate.window.resets_at);
    reset.dateTime = date.toISOString();
    reset.textContent = formatReset(candidate.window.resets_at).replace("Resets ", "");
    detail.textContent = `${accountLabel(candidate.snapshot)} · ${formatWindow(candidate.window.id)}`;
  } else {
    reset.removeAttribute("datetime");
    reset.textContent = state.loading ? "Waiting for sync" : "Not reported";
    detail.textContent = "No reset reported";
  }
}
```

Use DOM node creation rather than assigning server-controlled strings to `innerHTML`. The static headline fragments above are trusted text nodes created by `element()`.

- [ ] **Step 4: Update summary rendering to use signal-strip metrics**

Replace the current summary card data with exactly these values while retaining DOM construction through `element()`:

```javascript
const counts = snapshotCounts();
const cards = [
  ["Live now", `${counts.live} / ${state.snapshots.length}`, `${counts.live} reporting live`],
  ["Attention", String(counts.attention + counts.unavailable), counts.attention + counts.unavailable ? "accounts need a look" : "nothing needs a look"],
  ["Last sync", select("#last-updated")?.textContent?.replace("Synced ", "") || "—", state.accountLoadError || "local provider read"],
];
```

Keep the existing `#summary` element and render one card per tuple. The earliest reset belongs in the hero, not a duplicate summary card. Add a fourth “Action” card only when an unavailable account exists, using the existing attention color and a text label.

- [ ] **Step 5: Run the browser test and inspect the revised state**

Run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: the hero and signal strip render from live data, the test’s revised landmarks pass, and any remaining failure is limited to styling or interaction assertions.

- [ ] **Step 6: Commit the rendering model**

```bash
git add src/time_to_sleep/static/app.js
git commit -m "feat: render editorial usage summary"
```

## Task 4: Implement the dark editorial visual system and responsive ledger

**Files:**
- Modify: `src/time_to_sleep/static/styles.css`

- [ ] **Step 1: Replace the root tokens with the approved dark-first palette**

Use dark defaults and a warm paper light override. Keep the existing token names:

```css
:root {
  color-scheme: dark;
  --bg: #0f1413;
  --surface: #141c19;
  --surface-raised: #19221f;
  --text: #e7ede3;
  --muted: #9aa79d;
  --line: #2b3732;
  --accent: #d6f66c;
  --positive: #9ed8a4;
  --warning: #e0a36f;
  --danger: #ef8d83;
}

:root[data-theme="light"] {
  color-scheme: light;
  --bg: #eee9df;
  --surface: #f5f1e8;
  --surface-raised: #fbfaf5;
  --text: #292b26;
  --muted: #797970;
  --line: #c8c5b9;
  --accent: #6d8b32;
  --positive: #56835c;
  --warning: #b0653d;
  --danger: #a34f4c;
}
```

- [ ] **Step 2: Style the hero and signal strip as editorial regions**

Use left-aligned typography, a wide serif headline, and an offset reset aside:

```css
.hero { padding: clamp(72px, 12vw, 150px) 0 54px; }
.hero-row { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(210px, .65fr); gap: 48px; align-items: end; }
h1 { max-width: 760px; font-size: clamp(52px, 8vw, 104px); line-height: .88; letter-spacing: -.08em; }
h1 em { color: var(--accent); font-style: normal; }
.hero-copy { max-width: 520px; color: var(--muted); font-size: 16px; }
.hero-reset { border-left: 1px solid var(--line); padding-left: 24px; }
.reset-label, .summary-label { color: var(--muted); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; }
#next-reset { display: block; margin-top: 8px; font-family: Georgia, "Times New Roman", serif; font-size: clamp(28px, 4vw, 48px); line-height: 1; }
.reset-detail { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.signal-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; margin-bottom: 82px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.summary-card { min-height: 112px; padding: 20px 22px; background: transparent; }
.summary-card + .summary-card { border-left: 1px solid var(--line); }
```

- [ ] **Step 3: Turn account cards into a readable ledger**

Keep `.account-card` and the current status modifier classes because `app.js` emits them, but remove the generic rounded-card treatment:

```css
.account-list { gap: 0; border-top: 1px solid var(--line); }
.account-card { display: grid; grid-template-columns: minmax(220px, .8fr) minmax(0, 1.4fr); gap: 26px; padding: 24px 0; border: 0; border-bottom: 1px solid var(--line); background: transparent; }
.account-card-header { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(220px, .8fr) minmax(0, 1.4fr) 110px; gap: 26px; align-items: center; }
.provider-monogram { width: 34px; height: 34px; border-radius: 0; }
.window-list { grid-column: 2; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 0; padding-top: 0; border-top: 0; }
.button-action { justify-self: end; margin-top: 0; border-radius: 2px; }
.account-message, .account-error { grid-column: 1 / -1; }
```

If the existing DOM order prevents the intended grid alignment, add wrapper classes in `renderAccount()` rather than introducing a second data model.

- [ ] **Step 4: Add mobile layout, long-text safety, and motion rules**

At `max-width: 760px`, stack the hero, signal cards, account header, windows, and setup controls. Preserve actions and use `min-width: 0`, `overflow-wrap: anywhere`, and full-width buttons where needed:

```css
@media (max-width: 760px) {
  .app-shell { width: min(100% - 32px, 560px); }
  .hero-row, .account-card, .account-card-header { display: block; }
  .hero-reset { margin-top: 32px; border-left: 0; border-top: 1px solid var(--line); padding: 18px 0 0; }
  .signal-strip { grid-template-columns: 1fr; }
  .summary-card + .summary-card { border-top: 1px solid var(--line); border-left: 0; }
  .window-list { display: grid; grid-template-columns: 1fr; gap: 22px; margin-top: 22px; }
  .status-stack { align-items: flex-start; margin-top: 14px; }
  .status-note { max-width: none; text-align: left; }
  .button-action { width: 100%; margin-top: 18px; }
  .setup-controls { align-items: stretch; flex-direction: column; }
  .setup-controls .button { width: 100%; }
  .identity-copy h3, .account-meta, .account-message, .account-error { overflow-wrap: anywhere; white-space: normal; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
```

- [ ] **Step 5: Run visual and static checks**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run python tests/browser_dashboard.py
```

Expected: Python/static checks pass; the browser smoke test has no horizontal overflow at desktop or mobile and no console/page errors.

- [ ] **Step 6: Commit the visual system**

```bash
git add src/time_to_sleep/static/styles.css
git commit -m "feat: apply dark editorial dashboard styling"
```

## Task 5: Improve refresh, partial-failure, and setup feedback

**Files:**
- Modify: `src/time_to_sleep/static/app.js`
- Modify: `src/time_to_sleep/static/styles.css`

- [ ] **Step 1: Add explicit refresh state and independent account error rendering**

Update `refresh()` to announce progress, preserve visible snapshots, capture account metadata failure independently, and restore the button in `finally`:

```javascript
async function refresh(forceRefresh = false) {
  state.loading = true;
  state.loadError = null;
  state.accountLoadError = null;
  const button = select("#refresh-button");
  const list = select("#account-list");
  if (button) {
    button.disabled = true;
    button.textContent = forceRefresh ? "Refreshing…" : "Syncing…";
  }
  if (list) list.setAttribute("aria-busy", "true");
  const announcement = select("#live-announcement");
  if (announcement) announcement.textContent = forceRefresh ? "Refreshing usage data…" : "Loading usage data…";
  render();

  try {
    const [usageResult, accountsResult] = await Promise.allSettled([loadUsage(forceRefresh), loadAccounts()]);
    if (usageResult.status === "fulfilled") {
      state.snapshots = usageResult.value.accounts || [];
      updateTimestamp(usageResult.value.generated_at);
    } else {
      state.loadError = usageResult.reason?.message || "Usage could not be loaded.";
    }
    if (accountsResult.status === "fulfilled") state.accounts = accountsResult.value || [];
    else state.accountLoadError = accountsResult.reason?.message || "Account metadata could not be loaded.";
    if (announcement) announcement.textContent = usageResult.status === "fulfilled" ? "Usage data refreshed." : state.loadError;
  } finally {
    state.loading = false;
    if (list) list.removeAttribute("aria-busy");
    if (button) {
      button.disabled = false;
      button.textContent = "Refresh usage";
    }
    render();
  }
}
```

Add the account metadata error to the signal strip’s supporting detail and keep previous snapshots when the usage request fails.

- [ ] **Step 2: Add setup lifecycle semantics**

In `renderSetup()`, set a status attribute on the panel and a live status on the challenge message:

```javascript
panel.dataset.status = setup.status;
const status = element("p", {
  className: statusClass,
  text: setup.message || setupStatusMessage(setup.status),
  attributes: { role: "status", "aria-live": "polite" },
});
```

Update the status copy map to these complete messages:

```javascript
const setupMessages = {
  idle: "Choose a sign-in method to begin.",
  starting: "Opening an isolated Codex session…",
  pending: "Login attempt active. Finish the sign-in in the new window or with the device code.",
  succeeded: "Login verified for the configured account.",
  failed: "Codex completed, but the account identity did not match.",
  cancelled: "Login setup cancelled. You can start another attempt when ready.",
  expired: "This login attempt expired. Start a new one when ready.",
  error: "The login session could not be started. Check the message and try again.",
};
```

Use the existing `setup.challenge.auth_url`, `verification_url`, and `user_code` fields unchanged. Keep `stopLoginPolling()` in close/cancel/error terminal paths.

- [ ] **Step 3: Add visual treatments for pending, error, and unavailable states**

Add these CSS rules without relying on color alone:

```css
.account-card.status-unavailable, .account-card.status-rate_limited { border-left: 2px solid var(--warning); padding-left: 22px; }
.setup-panel[data-status="pending"] { border-color: var(--accent); }
.setup-panel[data-status="error"], .setup-panel[data-status="failed"], .setup-panel[data-status="expired"] { border-color: var(--danger); }
.setup-status { max-width: 680px; }
.setup-status-error::before { content: "Attention · "; font-weight: 700; }
.account-message, .account-error { max-width: 720px; }
```

Retain the explicit status text and do not remove the existing status badge/dot.

- [ ] **Step 4: Run the setup and refresh smoke checks**

Run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: refresh restores its button even when a request fails; setup challenge, copy, polling completion, and cancellation remain functional; there are no uncaught browser errors.

- [ ] **Step 5: Commit interaction feedback**

```bash
git add src/time_to_sleep/static/app.js src/time_to_sleep/static/styles.css
git commit -m "feat: clarify dashboard refresh and setup states"
```

## Task 6: Expand browser verification for responsive and failure states

**Files:**
- Modify: `tests/browser_dashboard.py`

- [ ] **Step 1: Add a narrow viewport assertion**

Add this function and call it from `main()` after `assert_setup_flow(browser)`:

```python
def assert_mobile_layout(browser: Browser) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark")
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        assert page.locator("#provider-ledger").is_visible()
        assert page.locator("#refresh-button").is_visible()
        assert_no_horizontal_overflow(page)
        page.locator("#theme-toggle").focus()
        assert page.locator("#theme-toggle").evaluate(
            "element => getComputedStyle(element).outlineStyle !== 'none'"
        )
    finally:
        page.close()
```

- [ ] **Step 2: Add a partial-failure browser case**

Add `assert_partial_failure(browser)` and call it from `main()` before the mobile case:

```python
def assert_partial_failure(browser: Browser) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    try:
        page.route(
            f"{BASE_URL}/v1/usage*",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Provider sync unavailable"}),
            ),
        )
        page.route(
            f"{BASE_URL}/v1/accounts",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="[]",
            ),
        )
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=10_000,
        )
        assert "Provider sync unavailable" in (
            page.locator("#live-announcement").text_content() or ""
        )
        assert page.locator("#account-list").is_visible()
    finally:
        page.close()
```

Keep the existing mocked Codex setup case; update only selectors or copy assertions that changed as part of the approved design.

- [ ] **Step 3: Verify the complete browser suite**

With the API running:

```bash
uv run python tests/browser_dashboard.py
```

Expected: all dashboard, setup, partial-failure, responsive, theme, focus, and console-error checks pass.

- [ ] **Step 4: Commit browser coverage**

```bash
git add tests/browser_dashboard.py
git commit -m "test: cover editorial dashboard states and mobile layout"
```

## Task 7: Run the full project verification and hand off

**Files:**
- No production file changes expected.

- [ ] **Step 1: Run Python tests and static checks**

Run:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: the full test suite passes, Ruff reports no formatting or lint errors, and `ty check` completes successfully.

- [ ] **Step 2: Run the browser test against the FastAPI app**

Start the server with:

```bash
uv run uvicorn time_to_sleep.api:app --host 127.0.0.1 --port 4141
```

In a second terminal run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: the dashboard renders all four configured records, the dark editorial hierarchy is present, theme persistence works, refresh/setup/failure states pass, mobile has no horizontal overflow, and console/page error lists are empty.

- [ ] **Step 3: Review the final diff for scope**

Run:

```bash
git status --short
git diff HEAD~6 --stat
git diff --check
```

Confirm that only the static dashboard, browser coverage, the approved design/spec/plan docs, and `.gitignore` changed. Do not modify provider/backend code as part of this refinement.

- [ ] **Step 4: Record the final handoff**

Report the implementation commits, verification commands, and any browser-environment limitation. If all checks pass, the next integration decision can be made from a clean, reviewable branch.
