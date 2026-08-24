# Time-to-Sleep

High-performance local usage observatory and quota tracker for AI coding assistants (**Codex**, **Claude Code**, and **Antigravity**).

Features a **compiled native Rust core** with an Axum HTTP/SSE server, embedded static Web UI dashboard, sub-microsecond CLI formatters, Ratatui TUI, SQLite history analytics engine, and a native **macOS SwiftUI Menu Bar companion app**.

---

## Performance Highlights

* ⚡ **Sub-Microsecond CLI Formatting**: `time-to-sleep prompt` executes in **`0.80 µs`** (down from 14.75 µs in Python).
* 🪶 **Ultra-Low Memory Footprint**: Drops idle resident memory from ~35 MB to **`< 4.9 MB`**.
* 📦 **Single Standalone Mach-O Binary**: **`4.9 MB`** release binary bundling the entire HTTP server, SQLite engine, SSE broadcaster, CLI tools, and embedded Web UI. Zero Python/uv runtime dependencies required for distribution.
* 🚀 **Fast SQLite History Engine**: Ingests 1,000 snapshots with 5-minute deduplication in **`1.82 ms`** (8.5x faster).

---

## Quick Start

```bash
# Build release binary
cargo build --release

# Start the background server and Web UI dashboard
./target/release/time-to-sleep serve --port 4141

# Print tabular usage status in terminal
./target/release/time-to-sleep status

# Shell prompt statusline (compact, starship, tmux, waybar, sketchybar, json)
./target/release/time-to-sleep prompt --format=compact
./target/release/time-to-sleep prompt --format=starship
./target/release/time-to-sleep prompt --format=tmux

# Interactive terminal dashboard (Ratatui)
./target/release/time-to-sleep tui

# Auto-discover local accounts on disk
./target/release/time-to-sleep discover --apply
```

Open the dashboard at <http://127.0.0.1:4141/>.

---

## macOS Menu Bar App

A lightweight native SwiftUI Menu Bar companion application is located in `macOS/`:

* **Live Quota in Menu Bar**: Displays peak active percentage (`19%`) directly in your menu bar.
* **Native Notifications**: Real-time alerts at 80% warning and 95% critical thresholds, plus reset notifications.
* **Self-Contained Bundle**: `Time-to-Sleep.app` directly bundles and executes the native Rust binary (`Contents/Resources/time-to-sleep`) without shell dependencies.
* **Build & Run**:
  ```bash
  cd macOS && ./build.sh
  open macOS/Time-to-Sleep.app
  ```

---

## API Endpoints

```bash
curl -s http://127.0.0.1:4141/v1/usage
curl -s 'http://127.0.0.1:4141/v1/usage?force_refresh=true'
curl -s http://127.0.0.1:4141/v1/analytics
curl -s http://127.0.0.1:4141/v1/history?hours=24
curl -s http://127.0.0.1:4141/v1/analytics/heatmap?days=7
curl -N -s http://127.0.0.1:4141/v1/events
```

* `/v1/usage`: Normalized usage records across all accounts with TTL caching.
* `/v1/analytics`: Consumption velocity ($\Delta \text{quota}/\text{hr}$), estimated runway, and smart routing recommendations.
* `/v1/history`: Multi-range historical snapshots.
* `/v1/analytics/heatmap`: 24-hour SQL aggregated hourly distribution over 7 or 30 days.
* `/v1/events`: Server-Sent Events (SSE) live push stream with 20s keepalive.

---

## Test Suites & Verification

```bash
# Run Rust test suite & linter
cargo test
cargo clippy -- -D warnings
cargo fmt --check

# Run benchmark suite
cargo run --release --bin benchmark
```

---

## Configuration

Account definitions are saved in `~/.config/time-to-sleep/settings.json` (or `config/accounts.toml`):

```json
{
  "accounts": [
    {
      "id": "codex-primary",
      "provider": "codex",
      "email": "wzf5350@gmail.com",
      "home": "~/.codex",
      "priority": 0,
      "warning_threshold": 80.0
    },
    {
      "id": "claude",
      "provider": "claude",
      "email": "wzf5350@gmail.com",
      "home": "~",
      "priority": 0,
      "warning_threshold": 80.0
    },
    {
      "id": "antigravity",
      "provider": "antigravity",
      "email": "wzf5350@gmail.com",
      "home": "~/.gemini/antigravity-cli",
      "priority": 0,
      "warning_threshold": 80.0
    }
  ]
}
```

Credentials are never committed and are resolved dynamically via macOS Keychain, local app servers, and CLI profiles.
