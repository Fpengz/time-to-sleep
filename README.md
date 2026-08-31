# Time-to-Sleep

High-performance local usage observatory and quota tracker for AI coding assistants (**Codex**, **Claude Code**, and **Antigravity**).

Time-to-Sleep ships as a compiled **Rust** core with an Axum HTTP/SSE server, embedded Web UI, CLI and Ratatui TUI, SQLite history/analytics, plus a native **macOS SwiftUI Menu Bar** companion.

---

## Performance Highlights

* ⚡ **Sub-Microsecond CLI Formatting**: `time-to-sleep prompt` executes in **`0.80 µs`** in the current benchmark suite.
* 🪶 **Low Idle Memory**: the native backend is designed to stay below the footprint of the previous Python runtime.
* 📦 **Single Native Binary**: the release binary bundles the HTTP server, SQLite engine, SSE broadcaster, CLI tools, and embedded Web UI with no Python/uv runtime dependency.
* 🚀 **Fast SQLite History Engine**: snapshot writes use 5-minute unchanged-value deduplication and rolling retention.
* 🗜️ **Compressed & Cache-Aware Delivery**: gzip/brotli response compression plus ETag-based `304` revalidation avoids re-shipping unchanged embedded assets.

---

## Quick Start

```bash
# Build release binary
cargo build --release

# Start the local server and Web UI dashboard
./target/release/time-to-sleep serve --port 4141

# Print tabular usage status
./target/release/time-to-sleep status

# Shell prompt/statusline formats
./target/release/time-to-sleep prompt --format=compact
./target/release/time-to-sleep prompt --format=starship
./target/release/time-to-sleep prompt --format=tmux

# Interactive terminal dashboard
./target/release/time-to-sleep tui

# Auto-discover local accounts and save them
./target/release/time-to-sleep discover --apply
```

Open the dashboard at <http://127.0.0.1:4141/>.

The server binds to loopback. The embedded browser UI is same-origin with the API; permissive browser CORS is intentionally not enabled.

---

## macOS Menu Bar App

A native SwiftUI Menu Bar companion lives in `macOS/`:

* **Live Quota in Menu Bar**: displays the highest active quota percentage.
* **Configurable Native Notifications**: warning and critical thresholds are configured per account (defaults: 80% warning, 95% critical), with reset notifications after high usage.
* **Self-Contained Bundle**: `Time-to-Sleep.app` bundles and launches the native Rust binary from `Contents/Resources/time-to-sleep`.
* **Popover-Gated History Fetch**: 24-hour trend history is fetched while the popover is visible, after the latest usage refresh has completed and been persisted.
* **Preferences**: add/edit/delete/discover accounts, configure warning/critical thresholds, and control background retrieval/cache TTLs.
* **Build & Run**:

  ```bash
  cd macOS
  ./build.sh
  open Time-to-Sleep.app
  ```

---

## API

Common endpoints:

```bash
curl -s http://127.0.0.1:4141/v1/usage
curl -s 'http://127.0.0.1:4141/v1/usage?force_refresh=true'
curl -s http://127.0.0.1:4141/v1/analytics
curl -s 'http://127.0.0.1:4141/v1/history?hours=24'
curl -s 'http://127.0.0.1:4141/v1/analytics/heatmap?days=7'
curl -N -s http://127.0.0.1:4141/v1/events
```

Key semantics:

* `/v1/usage` returns normalized snapshots and persists the newest history samples.
* `/v1/analytics` reports the currently limiting quota window, reset-aware burn rate, estimated runway, and routing recommendations.
* `/v1/history` accepts `hours=1..720` and returns persisted per-window observations.
* `/v1/analytics/heatmap` accepts `days=1..30` and reports hourly **recorded quota levels**; it is not a consumption-delta metric.
* `/v1/events` emits named `usage` and `analytics` SSE events with a 20-second keepalive.
* Invalid query ranges return JSON `400` responses; history-store failures are surfaced as JSON `500` responses rather than valid-looking empty arrays.

See [docs/API.md](docs/API.md) for the complete behavior contract.

---

## Configuration

The runtime configuration is JSON at:

```text
~/.config/time-to-sleep/settings.json
```

Set `TIME_TO_SLEEP_CONFIG_DIR` to override the configuration directory. A sibling `config.json` is accepted as a legacy fallback when `settings.json` is absent. The repository's `config/accounts.toml` is a reference example only; the Rust runtime does not load it.

Example:

```json
{
  "accounts": [
    {
      "id": "codex-primary",
      "provider": "codex",
      "email": "developer@example.com",
      "home": "~/.codex",
      "priority": 0,
      "warning_threshold": 80.0,
      "critical_threshold": 95.0,
      "auto_retrieval": true
    }
  ],
  "auto_retrieval": {
    "enabled": true,
    "poll_interval_secs": 60,
    "codex_ttl_secs": 180,
    "claude_ttl_secs": 300,
    "antigravity_ttl_secs": 90
  }
}
```

Existing settings that omit `critical_threshold` remain compatible and default to `95.0`.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for field semantics, discovery behavior, and alert configuration.

Credentials are not stored in the repository; providers resolve authentication from their local CLI/app-server environments.

---

## History & Analytics Notes

* Persisted samples prefer the provider's `observed_at` timestamp over local retrieval time.
* Unchanged values within five minutes are deduplicated.
* History retention is 30 days.
* Analytics are tracked per `(account_id, window_id)`, so a change in the currently limiting quota window cannot create a synthetic burn-rate jump.
* A meaningful downward quota jump is treated as a reset; velocity is calculated from the latest post-reset segment.
* On startup, analytics are seeded from persisted history so burn-rate/runway calculations survive daemon restarts.

---

## Test Suites & Verification

```bash
cargo fmt --check
cargo clippy -- -D warnings
cargo test
cargo run --release --bin benchmark
```

GitHub Actions additionally builds the release binary, compiles the macOS app, packages the DMG, and uploads the build artifact.

---

## Additional Documentation

* [API behavior](docs/API.md)
* [Configuration](docs/CONFIGURATION.md)
* [Improvement roadmap](docs/ROADMAP.md)

Historical design plans under `docs/plans/` and `docs/superpowers/` describe the evolution of the project and may reference superseded Python-era commands or architecture. The README and the dedicated current-state docs above are authoritative for the Rust implementation.
