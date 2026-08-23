# Efficiency and Energy Consumption Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement comprehensive CPU, energy, and disk I/O optimizations across the Python backend, macOS SwiftUI Menu Bar application, SQLite history store, CLI, and Web UI.

**Architecture:**
- **Backend:** Fast-path server probing before `ps`/`lsof` in Antigravity; 20s baseline TTL; in-memory Keychain token caching; SSE keepalive raised to 20s; lazy CLI imports.
- **macOS:** Static `DateFormatter` singletons; cached `.env` port resolution; timer tolerance and adaptive polling; clean subshell in `BackendRunner`.
- **Database:** Deduplicated snapshot insertion in `HistoryStore`; direct SQL aggregation in `get_hourly_heatmap`; auto-pruning.
- **Frontend:** Page visibility handling to throttle background timers.

**Tech Stack:** Python 3.12, FastAPI, SQLite, SwiftUI, JavaScript.

---

### Task 1: Optimize Antigravity Provider & Backend Retrieval Core

**Files:**
- Modify: `src/time_to_sleep/services.py`
- Modify: `src/time_to_sleep/providers/antigravity.py`
- Modify: `src/time_to_sleep/providers/claude.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_antigravity.py`

- [x] **Step 1: Set Antigravity baseline TTL**
  In `src/time_to_sleep/services.py`, change `DEFAULT_TTLS["antigravity"]` from `timedelta(0)` to `timedelta(seconds=20)`.
- [x] **Step 2: Add cached server fast-path probe in Antigravity**
  In `src/time_to_sleep/providers/antigravity.py`:
  - Store `_cached_server: _LocalServer | None` on `AntigravityProvider`.
  - In `_find_server()`, if `_cached_server` is present and matches the requested PID filter, call `await self._post_probe(_cached_server)`. If successful, return `_cached_server` immediately without running `ps` or `lsof`.
  - Update `_cached_server` when a valid server is discovered or started; clear it when communication fails.
- [x] **Step 3: Add in-memory Keychain token caching in Claude provider**
  In `src/time_to_sleep/providers/claude.py`:
  - Cache `_cached_token: str | None` in `ClaudeCredentialSource` to avoid repeated `security find-generic-password` subprocess calls.
  - Invalidate `_cached_token` if an HTTP 401 is encountered.
- [x] **Step 4: Run unit tests for providers and services**
  Execute `uv run pytest tests/test_services.py tests/test_antigravity.py tests/test_claude.py`.

---

### Task 2: Optimize FastAPI SSE Keepalive & History Database Engine

**Files:**
- Modify: `src/time_to_sleep/api.py`
- Modify: `src/time_to_sleep/history.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_history.py`

- [x] **Step 1: Increase SSE keepalive interval**
  In `src/time_to_sleep/api.py` (`events_stream`), increase the keepalive timeout from `1.0` second to `20.0` seconds:
  `msg = await asyncio.wait_for(queue.get(), timeout=20.0)`.
- [x] **Step 2: Add snapshot deduplication in HistoryStore**
  In `src/time_to_sleep/history.py`:
  - Track last inserted percentage per account/window: `_last_records: dict[tuple[str, str], tuple[float, datetime]]`.
  - Skip inserting records if `used_percent` is identical and less than 5 minutes have elapsed since the last observation.
- [x] **Step 3: Implement SQL-level aggregation for hourly heatmap**
  In `src/time_to_sleep/history.py` (`get_hourly_heatmap`):
  - Replace in-memory list iteration with a SQL query:
    ```sql
    SELECT CAST(strftime('%H', observed_at) AS INTEGER) AS hr,
           ROUND(AVG(used_percent), 1) AS avg_pct,
           COUNT(*) AS sample_cnt
    FROM usage_history
    WHERE observed_at >= ?
    GROUP BY hr
    ```
  - Map query results directly into `HourlyUsageDistribution` instances.
- [x] **Step 4: Add automatic rolling history pruning**
  In `src/time_to_sleep/history.py`, call `self.prune(max_days=30)` during `_init_db()` and in `record_snapshots()` on a rolling periodic basis.
- [x] **Step 5: Run history and API tests**
  Execute `uv run pytest tests/test_history.py tests/test_api.py`.

---

### Task 3: Optimize Codex Rollout History Scanning & CLI Startup

**Files:**
- Modify: `src/time_to_sleep/providers/codex.py`
- Modify: `src/time_to_sleep/cli.py`
- Modify: `tests/test_codex.py`
- Modify: `tests/test_cli.py`

- [x] **Step 1: Bounded shallow scan in Codex rollout fallback**
  In `src/time_to_sleep/providers/codex.py` (`_read_rollout_fallback`):
  - Limit glob depth to shallow session files (`sessions/*.jsonl`, `archived_sessions/*.jsonl`) or sort directories before inspecting files, taking at most 10 recent files.
- [x] **Step 2: Lazy-load heavy CLI modules for prompt and status**
  In `src/time_to_sleep/cli.py`:
  - Move imports of `uvicorn`, `curses`, and other heavy packages inside their respective command branches (`serve`, `tui`).
  - Keep `prompt` and `status` paths minimal for near-instant execution (<20ms).
- [x] **Step 3: Run Codex and CLI tests**
  Execute `uv run pytest tests/test_codex.py tests/test_cli.py`.

---

### Task 4: Optimize macOS Menu Bar App (SwiftUI & Process Management)

**Files:**
- Modify: `macOS/Sources/Monitor.swift`
- Modify: `macOS/Sources/Views.swift`
- Modify: `macOS/Sources/BackendRunner.swift`

- [x] **Step 1: Cache `.env` port and add timer tolerance in Monitor.swift**
  - In `UsageMonitor`, cache `cachedPort: Int?`. Only read `.env` once on startup or when explicitly invalidated.
  - In `init()`, configure `timer?.tolerance = 10.0` to permit macOS CPU power management coalescing.
- [x] **Step 2: Convert SwiftUI DateFormatters to static singletons**
  In `macOS/Sources/Views.swift`:
  - Create a static enum `SharedFormatters` with `static let isoFormatter` and `static let displayFormatter`.
  - Update `parseDate`, `formatResetsAt`, and `resetCountdown` to use `SharedFormatters`.
- [x] **Step 3: Clean subshell execution in BackendRunner.swift**
  In `macOS/Sources/BackendRunner.swift`:
  - Avoid `-il` interactive login shell. Use `zsh -c` with direct PATH resolution to start the backend.
- [x] **Step 4: Compile and test macOS App**
  Run `cd macOS && ./build.sh`.

---

### Task 5: Web UI Visibility Throttling & Full Verification

**Files:**
- Modify: `src/time_to_sleep/static/app.js`
- Modify: `docs/ROADMAP.md`

- [x] **Step 1: Add document visibility change listener in app.js**
  In `src/time_to_sleep/static/app.js`:
  - Listen to `visibilitychange`. When the document is hidden (`document.hidden`), skip non-essential interval re-rendering.
- [x] **Step 2: Update ROADMAP.md documentation**
  Update `docs/ROADMAP.md` with the new Efficiency & Low-Power Architecture section.
- [x] **Step 3: Run full verification suite**
  Run:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run ty check`
