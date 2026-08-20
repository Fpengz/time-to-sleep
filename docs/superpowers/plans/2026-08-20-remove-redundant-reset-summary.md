# Remove Redundant Reset Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant global reset summary and loopback note while preserving reset dates inside each account's usage window.

**Architecture:** Keep the existing static FastAPI-served frontend and account ledger. Delete only the hero DOM and CSS for the aggregate reset/trust copy, simplify `renderHero()` to update title and status copy, and continue using `renderWindow()` for account-specific reset dates.

**Tech Stack:** Static HTML, vanilla JavaScript, CSS, Playwright sync browser checks, pytest/uv.

---

### Task 1: Add regression assertions for the focused UI behavior

**Files:**
- Modify: `tests/browser_dashboard.py:34-80` and `tests/browser_dashboard.py:250-285`

- [x] **Step 1: Replace the global reset assertion with absence assertions**

In `assert_dashboard`, remove the assertion that `#next-reset` is visible. Add these assertions after the hero copy assertion:

```python
assert page.locator(".hero-reset").count() == 0
assert page.locator(".sync-note").count() == 0
```

- [x] **Step 2: Assert reset data remains in the account ledger**

In `assert_setup_flow`, replace the `#next-reset-detail` checks with:

```python
assert page.locator(".hero-reset").count() == 0
assert page.locator(".sync-note").count() == 0
account_reset = page.locator("#account-list .account-card").filter(has_text="Claude Code")
assert account_reset.locator(".window-detail").filter(has_text="Resets").count() == 1
assert "Five Hour" in account_reset.inner_text()
```

The existing fixture gives the Claude account a `five_hour` window with a reset timestamp, so this verifies reset timing remains attached to the provider row after the hero aggregate is removed.

- [x] **Step 3: Run the focused browser test to verify RED**

Run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: FAIL because the current page still renders `.hero-reset` and `.sync-note`.

### Task 2: Remove the redundant hero markup and dead aggregate rendering

**Files:**
- Modify: `src/time_to_sleep/static/index.html:36-54`
- Modify: `src/time_to_sleep/static/app.js:125-215`

- [x] **Step 1: Delete the hero reset aside and loopback note**

In `index.html`, keep the eyebrow, hero title, and `#hero-copy`; remove the entire `<aside class="hero-reset">…</aside>` block and the `<p class="sync-note">…</p>` block.

- [x] **Step 2: Remove aggregate reset calculation**

In `app.js`, delete `resetCandidates()` and change `renderHero()` so it only selects `#page-title` and `#hero-copy`, returns when either is missing, and retains the existing title/copy state logic. Remove the `candidate` declaration and all code that reads or writes `#next-reset` and `#next-reset-detail`.

The resulting function must retain these behaviors:

```javascript
function renderHero() {
  const title = select("#page-title");
  const copy = select("#hero-copy");
  if (!title || !copy) return;

  const counts = snapshotCounts();
  const total = state.snapshots.length;
  const clear = !total || counts.attention + counts.unavailable === 0;
  const loadIssue = loadIssueMessage();
  const emptyFailure = !total && !state.loading && Boolean(loadIssue);

  title.replaceChildren(
    element("span", { text: emptyFailure ? "No clear reading" : clear ? "A clear night" : "A little weather" }),
    element("br"),
    element("em", { text: emptyFailure ? "from the providers." : clear ? "for your quota." : "in the forecast." }),
  );
  if (!total) {
    copy.textContent = state.loading ? "Listening for provider usage…" : loadIssue || "Waiting for the first provider sync.";
  } else if (clear) {
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} reporting live.`;
  } else {
    const needsAttention = counts.attention + counts.unavailable;
    copy.textContent = `${counts.live} of ${total} ${total === 1 ? "account is" : "accounts are"} live; ${needsAttention} need${needsAttention === 1 ? "s" : ""} attention.`;
  }
  if (total && loadIssue) copy.textContent += ` Last sync issue: ${loadIssue}`;
}
```

- [x] **Step 3: Run the focused browser test to verify GREEN**

Run:

```bash
uv run python tests/browser_dashboard.py
```

Expected: PASS, including the per-account `.window-detail` reset assertion.

### Task 3: Remove unused CSS and run the full verification suite

**Files:**
- Modify: `src/time_to_sleep/static/styles.css:120-180`
- Modify: `docs/superpowers/plans/2026-08-20-remove-redundant-reset-summary.md`

- [x] **Step 1: Delete CSS for removed elements**

Remove the `.hero-reset`, `.reset-label`, `#next-reset`, `.reset-detail`, and `.sync-note` rules. Remove the mobile `.hero-reset` rule as well. Keep `.hero-row` because it still provides the hero content layout without changing the existing responsive structure.

- [x] **Step 2: Run the full checks**

Run each command:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: all commands exit with status 0.

- [x] **Step 3: Review the diff and confirm scope**

Run:

```bash
git diff --check
git status --short
git diff -- src/time_to_sleep/static/index.html src/time_to_sleep/static/app.js src/time_to_sleep/static/styles.css tests/browser_dashboard.py
```

Confirm only the approved frontend/test cleanup is present, and that `renderWindow()` plus its existing reset formatting remain unchanged.

- [x] **Step 4: Commit the implementation**

```bash
git add src/time_to_sleep/static/index.html src/time_to_sleep/static/app.js src/time_to_sleep/static/styles.css tests/browser_dashboard.py docs/superpowers/plans/2026-08-20-remove-redundant-reset-summary.md
git commit -m "fix: remove redundant hero reset summary"
```
