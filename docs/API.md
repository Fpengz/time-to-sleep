# API Behavior

This document describes the current Rust HTTP API exposed by Time-to-Sleep. The server is intended for local use and binds to `127.0.0.1`.

## Local-browser security model

The embedded Web UI and API share the same origin. The server therefore does **not** enable permissive browser CORS. Native clients, curl, the CLI, and the macOS companion are not browser-CORS clients and can continue to call the loopback API directly.

Unknown `/v1/*` GET routes return a JSON `404` response rather than falling through to the Web UI's SPA index.

## Usage

### `GET /v1/usage`

Optional query parameter:

- `force_refresh=true` bypasses provider cache reuse where supported.

The response contains normalized `UsageSnapshot` records for every configured account. A provider task failure is represented as an explicit `unavailable` snapshot instead of silently removing that account from the response.

A successful usage collection also attempts to persist history samples. Persistence failures are logged and do not replace the usage response with fabricated history data.

## Analytics

### `GET /v1/analytics`

Analytics are computed per account from the **currently limiting quota window**: the window with the highest current `used_percent`.

Each account analytics object may include:

- `current_percent`
- `limiting_window_id`
- `burn_rate_per_hour`
- `minutes_to_exhaustion`
- recommendation/status fields

Burn rate is derived from the history of the same quota window identified by `limiting_window_id`. Time-to-Sleep does not differentiate an account-level maximum whose underlying window identity may change over time.

A downward drop greater than five percentage points is treated as a quota reset. Burn rate and runway are derived only from the latest post-reset segment. Very small/non-positive rates are omitted.

At daemon startup, the analytics service is seeded from up to 24 hours of persisted history so burn-rate/runway calculations can continue across restarts.

## History

### `GET /v1/history`

Query parameters:

- `account_id` — optional account filter.
- `hours` — defaults to `24`; valid range is `1..=720`.

Persisted rows are per `(account_id, window_id)` observation. The storage layer prefers provider `observed_at` over local `retrieved_at`, so a cached read does not appear to be a fresh provider observation merely because it was retrieved later.

Unchanged values within five minutes are deduplicated. History is pruned on a rolling 30-day retention window.

Malformed persisted timestamps are treated as storage errors rather than silently replaced with the current time.

Invalid `hours` values return JSON `400`. Storage/query failures return JSON `500` rather than `200 []`.

## Hourly recorded-level distribution

### `GET /v1/analytics/heatmap`

Query parameters:

- `account_id` — optional account filter.
- `days` — defaults to `7`; valid range is `1..=30`.

The endpoint aggregates persisted `used_percent` observations by UTC hour. It is best interpreted as an hourly **recorded quota level distribution**, not as an amount of quota consumed during each hour and not as a burn-rate derivative.

Invalid `days` values return JSON `400`. Storage/query failures return JSON `500`.

## Server-Sent Events

### `GET /v1/events`

The SSE stream emits named events:

- `usage`
- `analytics`

Clients should subscribe using named event listeners rather than relying only on the default `message` event.

Example:

```js
const events = new EventSource('/v1/events');

events.addEventListener('usage', (event) => {
  const payload = JSON.parse(event.data);
  // update usage UI
});

events.addEventListener('analytics', (event) => {
  const payload = JSON.parse(event.data);
  // update analytics UI
});
```

The server subscribes the connection to broadcasts before assembling its initial usage/analytics state, reducing the initialization gap between initial data and live updates. A keepalive is sent every 20 seconds.

## Account/configuration endpoints

The API also exposes account discovery, account configuration, settings, and Codex-login lifecycle endpoints under `/v1/accounts` and `/v1/settings`.

Settings writes are persisted before the in-memory settings object is swapped, so a failed disk write does not leave runtime state ahead of the durable configuration.

Codex login uses a managed `codex app-server` child process. Failed handshakes, cancellation, expiry, and completed-record retention are bounded so failed login attempts do not intentionally leave long-lived child processes or unbounded in-memory records.

See [CONFIGURATION.md](CONFIGURATION.md) for the settings schema and threshold behavior.
