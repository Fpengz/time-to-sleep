# Bugfixes and macOS Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix frontend DOM thrashing bugs, make macOS hardcoded paths dynamic, and handle unhandled OS exceptions in the backend.

**Architecture:** Maintain existing codebase structure. Use targeted DOM updates instead of `.replaceChildren()`, resolve macOS paths via `NSHomeDirectory()`, and catch `OSError` in FastAPI routes.

**Tech Stack:** Static HTML, vanilla JavaScript, SwiftUI, FastAPI, Python.

---

### Task 1: Fix Backend Directory Creation Exceptions

**Files:**
- Modify: `src/time_to_sleep/api.py`

- [x] **Step 1: Catch `OSError` in `login_start`**
  Modify the `/login/start` route to catch `OSError` when `account.expanded_home.mkdir` fails due to permissions, returning a 500 `HTTPException` instead of crashing.

### Task 2: Fix Frontend DOM Thrashing

**Files:**
- Modify: `src/time_to_sleep/static/app.js`
- Modify: `src/time_to_sleep/static/index.html`

- [x] **Step 1: Remove empty datetime attribute**
  Remove the invalid `datetime=""` attribute from the `<time id="last-updated">` element in `index.html`.
- [x] **Step 2: Prevent DOM destruction during polling**
  In `app.js` `pollLogin`, if the login status is `pending`, directly update the text content of `#setup-panel .setup-status` rather than calling `renderSetup()`, which previously destroyed user selection by rebuilding the DOM every 2 seconds.
- [x] **Step 3: Prevent global DOM destruction on interval**
  In `app.js`, modify the 60-second `setInterval` to only call `updateTimestamp(state.lastGeneratedAt)` and skip the full `render()` call.

### Task 3: Fix macOS App Hardcoded Paths

**Files:**
- Modify: `macOS/Sources/BackendRunner.swift`
- Modify: `macOS/Sources/Monitor.swift`

- [x] **Step 1: Dynamically resolve paths in BackendRunner**
  Replace `/Users/zhoufuwang/projects/time-to-sleep` with `(NSHomeDirectory() as NSString).appendingPathComponent("projects/time-to-sleep")`.
- [x] **Step 2: Improve `.env` parsing in Monitor**
  Use the same `NSHomeDirectory()` logic. Improve string splitting using `line.split(separator: "=", maxSplits: 1)` and `trimmingCharacters` to allow for spaces around the equals sign.

### Task 4: Verify and Commit

- [x] **Step 1: Run backend tests**
  Run `uv run pytest` to ensure `api.py` changes are structurally sound.
- [x] **Step 2: Commit changes**
  Commit the files using Git.
