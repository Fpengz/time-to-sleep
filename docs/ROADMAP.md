# Time-to-Sleep Improvement Roadmap

This document outlines proposed improvements, feature expansions, and architectural enhancements for the **Time-to-Sleep** usage ledger backend, Web UI, and macOS Menu Bar application.

---

## 1. Predictive Analytics & Workload Optimization

### 1.1 "Time to Exhaustion" & Consumption Velocity Tracker ✅
- **Status:** Implemented in `time_to_sleep.services.AnalyticsService`.
- **Metrics:**
  - Velocity ($\Delta \text{quota} / \text{hr}$).
  - Estimated runway in minutes/hours to exhaustion.
  - Displayed in Web UI card metadata and CLI.

### 1.2 Smart Coding Agent Switching Advice ✅
- **Status:** Implemented in `AnalyticsService` & Web UI.
- **Rule Engine:**
  - Context-aware recommendations when a provider is near limit ($\ge 80\%$) suggesting healthy alternatives ($< 50\%$).
  - Recommended account pill badges and top-level advice banner (`💡`).

### 1.3 Local History & Trend Storage ✅
- **Status:** Implemented in `time_to_sleep.history.HistoryStore` (SQLite at `~/.config/time-to-sleep/history.db`).
- **Features:**
  - `GET /v1/history` endpoint with rolling 24-hour query.
  - Inline SVG sparkline charts rendered dynamically on each account card in the Web UI.

---

## 2. macOS Menu Bar & Desktop Integration

### 2.1 Glanceable Menu Bar Metrics ✅
- **Status:** Implemented in `macOS/Sources/App.swift`.
- **Features:**
  - Dynamic percentage in menu bar title reflecting highest active quota (e.g., `63%`).
  - Status indicator badges for warnings and rate limits.

### 2.2 Native Desktop Notifications (`UNUserNotificationCenter`) ✅
- **Status:** Implemented in `macOS/Sources/Monitor.swift`.
- **Triggers:**
  - **Threshold Warnings:** 80% warning and 95% critical warning alerts.
  - **Reset Completion:** Automatic detection when quota resets after high usage.

### 2.3 Menu Bar Quick Actions & UX ✅
- **Status:** Implemented in `macOS/Sources/App.swift`.
- **Features:**
  - Direct *"Dashboard ↗"* button opening local web interface.
  - Force Refresh and quick quit controls.
  - *"Launch at Login"* toggle via macOS `SMAppService.mainApp`.

---

## 3. Developer & Terminal Ergonomics

### 3.1 CLI Status & Terminal UI (TUI) ✅
- **Status:** Implemented in `time_to_sleep.cli`.
- **Commands:**
  - `uv run time-to-sleep status` (ANSI colored tabular view).
  - `uv run time-to-sleep tui` (interactive full-screen curses dashboard with keyboard shortcuts `r`, `f`, `q`).

### 3.2 Shell Prompt & Statusline Integration ✅
- **Status:** Implemented in `time_to_sleep.cli`.
- **Commands:**
  - `uv run time-to-sleep prompt --format=compact` (`[Codex:63% | Codex2:5% | Claude:! | AGY:5%]`).
  - `uv run time-to-sleep prompt --format=tmux` (tmux status bar formatting).

### 3.3 Real-Time Push via Server-Sent Events (SSE) ✅
- **Status:** Implemented in `time_to_sleep.api.EventBroadcaster`.
- **Endpoints:**
  - `GET /v1/events` stream for live updates.
  - Web UI `EventSource` subscriber for instant synchronization.

---

## 4. Deployment, Packaging & Configuration

### 4.1 Web UI Account Management ✅
- **Status:** Implemented in Web UI (`index.html`, `app.js`) & API.
- **Endpoints:**
  - `POST /v1/accounts/config` to add/edit accounts.
  - `DELETE /v1/accounts/config/{account_id}` to delete accounts.
  - Modal form for configuring account IDs, providers, emails, and home paths.

### 4.2 Automated Packaging & CI/CD ✅
- **Status:** Implemented in `.github/workflows/ci.yml` and `macOS/package_dmg.sh`.
- **Features:**
  - GitHub Actions matrix running formatting, linter, typecheck, and pytest.
  - macOS runner compiling Swift app and bundling `.dmg` installer.

---

## 5. Integration, Desktop Tools & Analytics Enhancements

### 5.1 Integration & Extensibility (Desktop Tools) ✅
- **Status:** Implemented in `time_to_sleep.cli`, `time_to_sleep.discovery`, and `integrations/raycast/`.
- **Features:**
  - `time-to-sleep prompt --format=json|sketchybar|waybar|compact|starship|tmux`.
  - `time-to-sleep discover [--apply] [--json]` CLI command and `/v1/accounts/discover` endpoint.
  - Official Raycast Script Command in `integrations/raycast/time-to-sleep.sh`.

### 5.2 Native macOS App Polish ✅
- **Status:** Implemented in `macOS/Sources/PreferencesView.swift` and `macOS/Sources/App.swift`.
- **Features:**
  - Rich Menu Bar popover window with live cards, mini SwiftUI sparkline graphs, and quota progress bars.
  - Native Account Preferences (`Cmd + ,`) window in Swift for adding, editing, deleting, and auto-discovering accounts with custom thresholds.

### 5.3 Web UI & Analytics Enhancements ✅
- **Status:** Implemented in `time_to_sleep.history.HistoryStore`, `time_to_sleep.api`, and Web UI.
- **Features:**
  - Interactive multi-range history selector (`24h`, `7d`, `30d`) with dynamic sparklines.
  - Hourly Usage Distribution heatmap graph (`GET /v1/analytics/heatmap`) showing 7-day average quota patterns.
  - Per-account custom warning (`warning_threshold`) and critical (`critical_threshold`) percentage alert limits.
  - 1-click Auto-Discovery modal in Web UI (`🔍 Discover`).

---

## 6. Efficiency, Energy & Low-Power Architecture ✅

### 6.1 Subprocess Elimination & Fast-Path Server Probing ✅
- **Status:** Implemented in `time_to_sleep.providers.antigravity` & `time_to_sleep.providers.claude`.
- **Features:**
  - In-memory cached server probing for Antigravity before spawning `ps` and `lsof` processes.
  - 20s baseline TTL for Antigravity in `UsageService`.
  - In-memory Keychain token caching in Claude provider to eliminate `security` CLI subprocesses with invalidation on HTTP 401.

### 6.2 macOS Power Management & Coalescing ✅
- **Status:** Implemented in `macOS/Sources/Monitor.swift` & `macOS/Sources/Views.swift`.
- **Features:**
  - Timer tolerance (`timer.tolerance = 10.0`) and concurrent `async let` fetching in `UsageMonitor`.
  - Static `SharedFormatters` singletons in SwiftUI rendering loops.
  - Cached `.env` port resolution to avoid repeated disk reads.
  - Clean `zsh -c` subshell launcher in `BackendRunner`.

### 6.3 SQLite Deduplication & SQL-Level Aggregation ✅
- **Status:** Implemented in `time_to_sleep.history.HistoryStore`.
- **Features:**
  - Deduplicated snapshot recording in `HistoryStore` (5-minute suppression for unchanged data).
  - Direct SQL-level aggregation `strftime('%H', observed_at)` for hourly usage heatmaps.
  - Automated rolling 30-day history retention pruning.

### 6.4 Event Loop Wakeup Reduction & CLI Latency ✅
- **Status:** Implemented in `time_to_sleep.api` and `src/time_to_sleep/static/app.js`.
- **Features:**
  - SSE keepalive interval increased from 1.0s to 20.0s (95% reduction in timer wakeups).
  - EventBroadcaster subscriber gating on payload generation.
  - Web UI tab visibility handling (`document.visibilityState`) to pause idle background timers.

---

## 7. Native Rust Core & Modern UI Redesign ✅

### 7.1 Full Rust Backend & CLI (`time-to-sleep`) ✅
- **Status:** Implemented in `src/` and `Cargo.toml`.
- **Features:**
  - Standalone **4.9 MB** Mach-O binary compiled with Axum, Tokio, Rusqlite, Clap, and Ratatui.
  - **0.80 µs** per-invocation prompt formatting latency (18.4x faster than Python).
  - **1.82 ms** SQLite ingestion for 1,000 snapshots (8.5x faster).
  - Idle resident memory dropped to **< 4.9 MB** (7.1x less RAM).
  - Embedded static web assets directly into the binary via `rust-embed` from `static/`.

### 7.2 Web Dashboard Visual & Ergonomic Redesign ✅
- **Status:** Implemented in `static/styles.css` and `static/app.js`.
- **Features:**
  - Clean, high-contrast dark/light design system (Slate / Obsidian / Emerald / Coral).
  - Re-architected window cards with title + duration badge on the left, large bold usage percentage on the right, and rounded animated progress meters.
  - Compact velocity & runway status bar with emoji indicators.
  - High-resolution SVG sparklines with gradient area fills and drop-shadow glow.

### 7.3 Native macOS Bundle Integration ✅
- **Status:** Implemented in `macOS/Sources/BackendRunner.swift` & `macOS/build.sh`.
- **Features:**
  - `Time-to-Sleep.app` directly bundles the compiled release binary (`Contents/Resources/time-to-sleep`).
  - Spawns the native binary directly without shell or interpreter dependencies.

---

## 8. Delivery Optimization & Icon Refresh ✅

### 8.1 Compressed & Cache-Aware HTTP Delivery ✅
- **Status:** Implemented in `src/api/routes.rs` and `Cargo.toml` (`tower-http` compression features).
- **Features:**
  - `CompressionLayer` (gzip/brotli) on all JSON API responses and embedded static assets, shrinking `app.js` transfer size by ~76% (65KB → 16KB gzipped).
  - ETag generation from `rust-embed`'s baked-in SHA-256 hash with `If-None-Match` → bodyless `304` support, so repeat dashboard loads skip re-downloading unchanged JS/CSS.
  - `text/event-stream` (SSE) responses are excluded from compression so live push isn't buffered or delayed.

### 8.2 Web UI Render Coalescing ✅
- **Status:** Implemented in `static/app.js`.
- **Features:**
  - The server always broadcasts a `usage` and `analytics` SSE event back-to-back per update cycle; both now funnel through a `requestAnimationFrame`-batched `scheduleRender()` instead of triggering two independent full DOM rebuilds.

### 8.3 macOS Menu Bar Icon Suite Refresh ✅
- **Status:** Implemented in `macOS/generate_icons.py`, `macOS/AppIcon.icns`, `macOS/MenuIcon.png`.
- **Features:**
  - Repeatable icon pipeline (squircle masking, iconset compilation, `.icns` build via `iconutil`) selectable with `python3 macOS/generate_icons.py --concept <1-4>`.
  - Active concept: **Celestial Chronometer** — a solid-filled crescent moon with a cyan/indigo quota ring, chosen over the initial neon-outline concept because it stays legible at real 16-32px Dock/menu-bar sizes.
  - Dynamic light/dark `MenuIcon.png` template icon, verified to tint correctly in both appearance modes.



