# Time-to-Sleep Roadmap

This roadmap describes the **current Rust implementation** and the next practical improvement areas for the backend, Web UI, CLI/TUI, SQLite analytics, and macOS companion.

Historical design documents under `docs/plans/` and `docs/superpowers/` are retained as project history. They may reference the earlier Python implementation, `uv run` commands, or superseded architecture and are not the authoritative runtime documentation.

For current behavior, see:

- [README.md](../README.md)
- [API.md](API.md)
- [CONFIGURATION.md](CONFIGURATION.md)

---

## Current Architecture Baseline

Time-to-Sleep currently consists of:

- a native Rust binary using Axum, Tokio, Rusqlite, Clap, Ratatui, and embedded static assets;
- provider adapters for Codex, Claude Code, and Antigravity;
- a loopback HTTP API and named Server-Sent Events stream;
- SQLite history with deduplication and rolling retention;
- per-window analytics for burn rate, runway, and routing recommendations;
- an embedded Web dashboard;
- a native SwiftUI macOS Menu Bar companion that bundles the Rust backend.

The supported runtime configuration is JSON at `~/.config/time-to-sleep/settings.json` (or under `TIME_TO_SLEEP_CONFIG_DIR`).

---

## Completed: Reliability & Correctness Hardening ✅

### Local API boundary

- Removed permissive wildcard browser CORS from the loopback daemon.
- Unknown `/v1/*` GET paths return JSON `404` rather than SPA HTML.
- History query ranges are bounded (`hours=1..720`, `days=1..30`).
- SQLite/history failures are surfaced as errors instead of valid-looking empty payloads.
- Blocking SQLite and filesystem work in API paths is moved off Tokio worker threads where appropriate.
- Settings are persisted before in-memory state is replaced.

### Server-Sent Events

- Live broadcasts preserve named `usage` and `analytics` event types.
- Connections subscribe before initial state is assembled, reducing the initial snapshot/live-update gap.
- SSE keepalive remains 20 seconds.

### Analytics correctness

- Analytics history is keyed by `(account_id, window_id)` rather than one account-level maximum series.
- Burn rate and runway are computed from the same quota window that is currently limiting the account.
- `limiting_window_id` identifies that window in API analytics responses.
- Meaningful downward quota jumps are treated as resets; velocity is computed from the latest post-reset segment.
- Provider `observed_at` is preferred over retrieval time for analytics/history semantics.
- Analytics are seeded from persisted history at startup to preserve continuity across daemon restarts.

### History persistence

- The in-memory dedup cache is updated only after a successful SQLite commit.
- Failed transactions can be retried without suppressing the retry as a duplicate.
- Malformed persisted timestamps are reported as errors rather than replaced with the current time.
- A window-aware `(account_id, window_id, observed_at)` index supports analytics/history access.
- Persistent-store fallback to in-memory history is explicitly reported.
- Direct CLI fallback history writes no longer silently discard persistence errors.

### Provider and login lifecycle

- Provider task panics/join failures produce an explicit unavailable account snapshot instead of silently removing the account.
- Codex login subprocesses use kill-on-drop protection during pre-registration handshake failures.
- Login home-directory setup uses async filesystem operations.
- Completed login records have bounded retention.
- Expired/cancelled sessions terminate their child process.
- Completion events must match the expected login ID when one exists.

### Configuration and native alerts

- `critical_threshold` is now a real persisted per-account field.
- Existing configurations that omit it default to `95.0`.
- Warning and critical thresholds are editable in Web/macOS preferences.
- macOS notifications honor configured per-account warning and critical thresholds instead of hardcoded values.
- Newly discovered accounts receive default warning/critical values and background retrieval enabled.

### Trend consistency and terminology

- Web history/heatmap reads are sequenced after the usage request that persists the newest observation.
- macOS visible history is likewise fetched after usage refresh completion.
- The hourly heatmap is described as a **recorded quota level** distribution, not as hourly quota consumption.

### CI baseline

- `cargo fmt --check`, Clippy with `-D warnings`, and the Rust test suite are clean.
- GitHub Actions builds the Rust release binary, compiles the macOS app, packages the DMG, and uploads the artifact.

---

## Next: Observability & Operational Diagnostics

### Structured backend diagnostics

Potential improvements:

- standardize structured tracing fields for provider failures, history degradation, and login lifecycle events;
- expose a small local health/degraded-state endpoint so clients can distinguish persistent-history fallback from normal operation;
- surface last successful persistence/collection timestamps in diagnostics without exposing credentials.

### Storage schema evolution

As the history schema grows:

- introduce explicit SQLite schema versioning/migrations;
- document migration and rollback expectations;
- add migration tests against representative older database versions.

---

## Next: Browser-Level Integration Coverage

The Rust API and macOS build paths have regression coverage, but the embedded dashboard would benefit from lightweight browser integration tests for:

- named SSE event handling;
- refresh ordering (`usage` before history/heatmap);
- account threshold editing and persistence;
- unknown API route behavior from the browser client;
- dashboard behavior when history is temporarily unavailable.

These tests should validate behavior without duplicating the Rust unit/integration suite.

---

## Next: Analytics Presentation

The backend now exposes `limiting_window_id`. Follow-up UI improvements can make that attribution more explicit:

- label burn rate/runway with the limiting window name/duration;
- distinguish short-window exhaustion from longer weekly limits visually;
- optionally show per-window velocity when enough observations exist;
- add confidence/insufficient-history states instead of implying an estimate when only one usable sample exists.

The core rule should remain: never derive a velocity across different quota-window identities or across a detected reset.

---

## Next: History & Heatmap Semantics

The current heatmap averages recorded `used_percent` observations by UTC hour. Future analytics could add separate metrics for actual change over time, for example:

- per-window hourly delta/burn summaries;
- reset-aware consumption accumulation;
- local-time presentation while retaining UTC timestamps in storage;
- explicit window filters for the heatmap.

Any new consumption metric should remain separate from the existing recorded-level distribution to avoid semantic ambiguity.

---

## Next: Configuration UX

Potential refinements:

- validate threshold ordering and numeric ranges server-side as well as in clients;
- show configuration persistence failures consistently in Web and macOS clients;
- make the runtime JSON path and legacy fallback visible in diagnostics/preferences;
- consider retiring or relocating the repository's reference `config/accounts.toml` if it continues to be mistaken for a runtime-loaded file.

---

## Next: Packaging & Release Discipline

Recommended release improvements:

- publish release notes that call out configuration-schema additions such as `critical_threshold`;
- verify upgrade compatibility from settings files created before new fields existed;
- retain CI checks for formatting, Clippy, tests, Rust release build, macOS build, DMG packaging, and artifact upload;
- add a small smoke test against the packaged binary/app where practical.

---

## Documentation Policy

Current-state documentation should live in the README and dedicated docs such as `API.md` and `CONFIGURATION.md`.

Historical implementation plans should generally remain unchanged so they continue to record design evolution. When an old plan conflicts with current behavior, prefer adding or updating current-state documentation rather than rewriting the historical record.
