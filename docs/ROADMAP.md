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


