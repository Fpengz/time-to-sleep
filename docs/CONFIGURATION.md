# Configuration

Time-to-Sleep persists runtime settings as JSON.

## Settings path

Default path:

```text
~/.config/time-to-sleep/settings.json
```

Set `TIME_TO_SLEEP_CONFIG_DIR` to override the directory. When `settings.json` is absent, a sibling `config.json` is accepted as a legacy fallback.

The repository file `config/accounts.toml` is a human-readable reference/example only. The current Rust runtime does not load TOML configuration.

If no persisted JSON configuration exists, Time-to-Sleep auto-discovers local provider accounts, constructs default settings, and attempts to save them to `settings.json`.

## Schema

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

## Account fields

### `id`

Stable local identifier for the configured account. API caches, analytics, history, and login attempts use this identifier.

### `provider`

One of:

- `codex`
- `claude`
- `antigravity`

### `email`

Configured account label/identity. Providers may also return an observed email at runtime.

### `home`

Provider-specific local home/configuration directory. A leading `~` is expanded to the current user's home directory.

### `priority`

Integer priority field retained in account configuration. Defaults to `0` when omitted.

### `warning_threshold`

Per-account warning percentage. Defaults to `80.0` for legacy/missing values.

Analytics uses this threshold when deciding whether an account is near its configured limit and should trigger routing suggestions.

The macOS companion also reads the configured threshold for native warning notifications.

### `critical_threshold`

Per-account critical percentage. Defaults to `95.0` for settings created before this field existed.

The Web UI and macOS Preferences both persist this value. The macOS companion uses it for critical notifications rather than a hardcoded 95% threshold.

Preferences keep the critical value greater than or equal to the warning value when editing thresholds.

### `auto_retrieval`

Per-account switch controlling whether background provider retrieval is allowed. Defaults to `true`.

## Global auto-retrieval fields

### `enabled`

Master background-retrieval switch. Defaults to `true`.

### `poll_interval_secs`

Background polling cadence used by clients such as the macOS companion. Default: `60` seconds.

### Provider TTLs

Defaults:

- `codex_ttl_secs`: `180`
- `claude_ttl_secs`: `300`
- `antigravity_ttl_secs`: `90`

`UsageService` uses the provider-specific TTL to decide when an existing cached snapshot can be reused instead of performing another provider request.

## Discovery

Time-to-Sleep can inspect known local provider locations:

```bash
./target/release/time-to-sleep discover
./target/release/time-to-sleep discover --apply
./target/release/time-to-sleep discover --json
```

Equivalent API endpoints are available under `/v1/accounts/discover`.

Newly discovered accounts receive the standard defaults, including an 80% warning threshold, a 95% critical threshold, and background retrieval enabled.

## Editing and persistence semantics

The Web UI and macOS Preferences use the local API to add/edit/delete accounts and update global retrieval settings.

Settings writes are written to disk before the server replaces its in-memory settings snapshot. A persistence failure therefore returns an error instead of pretending the change succeeded only in memory.

The global settings update endpoint intentionally preserves the server's current account list while updating global auto-retrieval settings. Account mutations use the dedicated account configuration endpoints.

## Credentials

The settings file contains account metadata and local paths, not provider passwords. Provider authentication is resolved from the provider's normal local environment, CLI credentials, keychain entries, or local app-server session.
