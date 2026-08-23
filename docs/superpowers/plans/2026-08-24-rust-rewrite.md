# Rust Backend & CLI Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a high-performance, low-power Rust binary replacing the Python backend and CLI while preserving complete API and data compatibility with the Swift macOS Menu Bar app and existing SQLite database.

---

### Task 1: Initialize Cargo Package & Core Domain Models

**Files:**
- Create: `Cargo.toml`
- Create: `rust/src/lib.rs`
- Create: `rust/src/domain.rs`

- [x] **Step 1: Create `Cargo.toml`**
  Add dependencies: `tokio`, `axum`, `serde`, `serde_json`, `rusqlite`, `reqwest`, `clap`, `chrono`, `tracing`, `tracing-subscriber`, `ratatui`, `crossterm`, `rust-embed`.
- [x] **Step 2: Implement Domain Models in Rust**
  Port `ProviderName`, `AccountStatus`, `ErrorCode`, `AccountConfig`, `UsageWindow`, `UsageSnapshot`, `AccountAnalytics`, `AnalyticsResponse`, and `Settings`.
- [x] **Step 3: Add Serde Unit Tests**
  Verify bidirectional JSON serialization matches Python schema exactly.
- [x] **Step 4: Run `cargo test domain`**.

---

### Task 2: Implement SQLite History Storage & Deduplication

**Files:**
- Create: `rust/src/history.rs`

- [x] **Step 1: SQLite Connection & Schema Management**
  Create `HistoryStore` with `rusqlite` connection pool / mutex.
  Initialize table `usage_history` and index `idx_history_account_time`.
- [x] **Step 2: Implement Deduplicated Snapshot Recording**
  Implement `record_snapshots` with 5-minute duplicate suppression.
- [x] **Step 3: Implement SQL-Level Hourly Heatmap Aggregation**
  Implement `get_hourly_heatmap` using `strftime('%H', observed_at)` and `AVG(used_percent)`.
- [x] **Step 4: Implement 30-day History Pruning**
- [x] **Step 5: Run `cargo test history`**.

---

### Task 3: Implement Provider Adapters & In-Memory Caching

**Files:**
- Create: `rust/src/providers/mod.rs`
- Create: `rust/src/providers/codex.rs`
- Create: `rust/src/providers/claude.rs`
- Create: `rust/src/providers/antigravity.rs`

- [x] **Step 1: Codex Adapter**
  - Implement JSON-RPC app-server transport over async child process.
  - Implement fast rollout fallback parser for `.jsonl` files.
- [x] **Step 2: Claude Adapter**
  - Read token from macOS Keychain (or `CLAUDE_CODE_OAUTH_TOKEN` env) with in-memory caching.
  - Fetch usage from Anthropic API.
- [x] **Step 3: Antigravity Adapter**
  - Language server discovery with cached server probe fast-path.
  - POST probe to Unleash / UserStatus endpoints.
- [x] **Step 4: Run `cargo test providers`**.

---

### Task 4: Implement UsageService, Analytics Engine & Account Discovery

**Files:**
- Create: `rust/src/services/usage.rs`
- Create: `rust/src/services/analytics.rs`
- Create: `rust/src/config.rs`
- Create: `rust/src/discovery.rs`

- [x] **Step 1: Implement `UsageService`**
  In-memory TTL cache (`tokio::sync::RwLock`), parallel provider dispatching with timeouts.
- [x] **Step 2: Implement `AnalyticsService`**
  Burn rate calculation, minutes to exhaustion, single-pass lowest usage recommendation.
- [x] **Step 3: Implement `config.rs` and `discovery.rs`**
  Read/write `~/.config/time-to-sleep/settings.json`, scan local directories for accounts.
- [x] **Step 4: Run `cargo test services`**.

---

### Task 5: Implement Axum Web Server, SSE Broadcaster & CLI

**Files:**
- Create: `rust/src/api/routes.rs`
- Create: `rust/src/api/sse.rs`
- Create: `rust/src/cli/formatters.rs`
- Create: `rust/src/cli/tui.rs`
- Create: `rust/src/main.rs`

- [x] **Step 1: Implement Axum REST Endpoints**
  `/v1/usage`, `/v1/analytics`, `/v1/history`, `/v1/analytics/heatmap`, `/v1/events` (with 20s keepalive).
- [x] **Step 2: Embedded Static Web Assets**
  Embed `static/index.html`, `app.js`, `style.css` via `rust-embed`.
- [x] **Step 3: Implement CLI Subcommands**
  `serve`, `status`, `prompt` (compact, json, starship, tmux, waybar, sketchybar), `tui` (ratatui), and `discover`.
- [x] **Step 4: Run `cargo test`**.

---

### Task 6: macOS Menu Bar App Integration & End-to-End Verification

**Files:**
- Modify: `macOS/Sources/BackendRunner.swift`
- Modify: `macOS/build.sh`

- [x] **Step 1: Update `BackendRunner.swift` to launch native Rust binary**
- [x] **Step 2: Build release binary (`cargo build --release`) and compile macOS app**
- [x] **Step 3: Verify end-to-end functionality & measure memory/CPU**
