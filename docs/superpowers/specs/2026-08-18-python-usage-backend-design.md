# Time-to-Sleep Python Usage Backend Design

Date: 2026-08-18

## Goal

Replace the current Node/Vite monitor with a Python-first backend whose primary responsibility is retrieving and normalizing usage data for four configured accounts:

- Codex: `wzf5350@gmail.com`
- Codex: `wzf0513@gmail.com`
- Claude: `wzf5350@gmail.com`
- Antigravity: `wzf5350@gmail.com`

The backend must be consumable by a future web UI, TUI, desktop app, or other client. The first implementation does not preserve the existing Node server, Vite development workflow, or `/api/usage` response contract.

## Design decisions

### Backend-first, client-agnostic core

The system is split into a provider-neutral usage domain and provider-specific adapters. FastAPI is an HTTP delivery layer over the same application services that a future TUI or desktop client can call.

The first release has no frontend scope. The old React/Vite files and Node server are removed as part of the migration so there is one authoritative runtime and one development toolchain.

### Provider-native retrieval with cached fallbacks

Provider adapters use the most authoritative interface available, but every result carries its source and freshness state.

1. Codex uses the installed `codex app-server` JSON-RPC interface. It calls `account/read` for identity and `account/rateLimits/read` for live quota windows. This delegates OAuth refresh and provider HTTP details to the official Codex client.
2. Claude uses the local Claude Code credential source and the OAuth usage endpoint when a valid credential is available. On macOS, the adapter reads the Claude Code Keychain item without exposing the token; on Linux/Windows it supports `.credentials.json` and environment-provided credentials. Because the OAuth usage endpoint is undocumented and rate-limited, it is cached and never polled on every request.
3. Claude falls back to Claude Desktop/Code local plan usage history when live OAuth data is unavailable. The fallback exposes the recorded five-hour and seven-day percentages, marks reset timestamps as unknown when the artifact does not contain them, and reports the result as cached or stale.
4. Antigravity remains local-log based. The adapter tails the configured language-server log, parses the latest quota event and reset duration, and reports a stale/unavailable state when no recent event exists.
5. Codex and Claude local artifacts are fallbacks only. A historical snapshot is never presented as live data.

### Freshness is part of the public model

Each account result includes:

- `status`: `live`, `cached`, `stale`, or `unavailable`
- `source`: the concrete adapter source, such as `codex_app_server`, `claude_oauth`, `claude_plan_history`, or `antigravity_log`
- `observed_at`: when the provider or local artifact reported the value
- `retrieved_at`: when this backend read the source
- `message`: actionable diagnostics when the value is incomplete or unavailable

The service returns partial success: one provider failure does not prevent the other accounts from being returned.

## Account configuration

Configuration moves from the root `accounts.json` file to a typed TOML configuration under `config/accounts.toml` (with an environment variable override for deployments). Credentials are never committed.

The initial configuration is conceptually:

```toml
[[accounts]]
id = "codex-primary"
provider = "codex"
email = "wzf5350@gmail.com"
home = "~/.codex"

[[accounts]]
id = "codex-secondary"
provider = "codex"
email = "wzf0513@gmail.com"
home = "~/.config/time-to-sleep/accounts/codex-secondary"

[[accounts]]
id = "claude"
provider = "claude"
email = "wzf5350@gmail.com"
home = "~/.claude"

[[accounts]]
id = "antigravity"
provider = "antigravity"
email = "wzf5350@gmail.com"
home = "~/.config/Antigravity"
```

`home` is an input path, not a credential itself. The service expands `~` at runtime, validates that it is a directory or a permitted profile location, and never returns credential contents.

The expected email is used as an identity assertion. If a provider reports a different email, the account is marked misconfigured rather than silently attributing usage to the wrong account.

## Codex login setup flow

The secondary Codex account starts without a local home. The backend creates the configured profile directory with restrictive permissions and runs `codex app-server` with `CODEX_HOME` pointed at that profile.

The lifecycle is:

1. A client calls `POST /v1/accounts/codex-secondary/login/start` with `method = browser` or `method = device_code`.
2. The service starts an app-server subprocess, performs the JSON-RPC initialization handshake, and sends `account/login/start` with the selected login type.
3. For browser login, the response contains the provider-generated authorization URL. For device-code login, it contains the verification URL and user code.
4. The service retains the pending app-server process in a bounded login-attempt registry and consumes `account/login/completed` notifications in the background.
5. On success, the service calls `account/read`, verifies `wzf0513@gmail.com`, and marks the profile ready. The login subprocess is then closed; later usage reads start a fresh short-lived app-server process.
6. On mismatch, timeout, cancellation, or provider error, the attempt is marked failed with an actionable message. Tokens are never returned by the API.

Login attempts are local-only operations by default. The FastAPI server binds to `127.0.0.1`, and login endpoints are not exposed through a permissive CORS policy. A future remote deployment must add explicit authentication before enabling these operations.

## Internal architecture

The Python package is organized around small boundaries:

- `config`: typed settings and account loading
- `domain`: Pydantic models for accounts, windows, snapshots, freshness, and login attempts
- `providers`: provider adapters and source-specific parsers
- `services`: concurrent account collection, cache policy, login orchestration, and identity verification
- `api`: FastAPI routes and dependency wiring
- `cli`: local development and diagnostic commands, if needed later

The provider interface is asynchronous from the service perspective and returns a normalized result. Adapters may use async HTTP or an async subprocess. Blocking parsing is bounded to small tails or streaming reads so a large session history cannot block the event loop.

Account collection runs providers independently with per-account timeouts. A slow or broken app-server process is terminated and converted into an account-level diagnostic. A shared in-memory cache prevents repeated provider calls while preserving the last successful result for fallback display.

## HTTP contract

The new contract is versioned under `/v1`.

### `GET /health`

Returns process health and configuration load status. It does not contact providers.

### `GET /v1/accounts`

Returns configured account metadata, discovered provider identity, login readiness, and credential/source diagnostics. It does not return secrets.

### `GET /v1/usage`

Collects all configured accounts concurrently and returns:

```json
{
  "generated_at": "2026-08-18T00:00:00Z",
  "accounts": [
    {
      "id": "codex-primary",
      "provider": "codex",
      "configured_email": "wzf5350@gmail.com",
      "observed_email": "wzf5350@gmail.com",
      "status": "live",
      "source": "codex_app_server",
      "observed_at": "2026-08-18T00:00:00Z",
      "retrieved_at": "2026-08-18T00:00:01Z",
      "plan_type": "team",
      "windows": [
        {
          "id": "primary",
          "used_percent": 15.0,
          "window_minutes": 10080,
          "resets_at": "2026-08-22T00:00:00Z"
        }
      ],
      "message": null
    }
  ]
}
```

Missing windows are represented as `null`/omitted values rather than fabricated zeros. The endpoint supports a refresh hint for clients, but provider-specific throttle policies still apply.

### Codex login routes

- `POST /v1/accounts/{account_id}/login/start`
- `GET /v1/accounts/{account_id}/login/{attempt_id}`
- `POST /v1/accounts/{account_id}/login/{attempt_id}/cancel`

Only Codex accounts support the initial login flow. The API returns challenge data and state, never access or refresh tokens.

## Error handling and resilience

Errors are classified into actionable categories:

- `not_configured`: profile or required executable is missing
- `not_authenticated`: no usable credential exists
- `authentication_expired`: the provider credential exists but is rejected or expired
- `rate_limited`: the live source asked the backend to slow down
- `parse_error`: local data exists but is malformed or an unrecognized schema
- `timeout`: provider process or HTTP request exceeded its deadline
- `identity_mismatch`: the provider account does not match configured email
- `no_recent_data`: only stale or absent local data is available

No exception from one account escapes the aggregate collection endpoint. Internal logs include provider, account id, source, and error category, but redact paths where appropriate and never log tokens, authorization headers, raw credential files, or full user transcripts.

## Toolchain and repository migration

The repository becomes a Python project managed by `uv`:

- `pyproject.toml` contains project metadata, runtime dependencies, Ruff configuration, and Ty configuration.
- `uv.lock` is committed for reproducible environments.
- FastAPI and Uvicorn provide the HTTP runtime.
- `ruff` provides formatting and linting.
- `ty` provides static type checking.
- `pytest` plus HTTP/subprocess fakes provide automated tests.

The standard local commands are:

```text
uv sync
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest
uv run uvicorn time_to_sleep.api:app --reload
```

The old `package.json`, `package-lock.json`, `server.mjs`, Vite configuration, React entrypoint, and frontend-only assets are removed or replaced during implementation. No compatibility shim is added for the old Node process or `/api/usage` endpoint.

## Testing strategy

### Unit tests

- Normalize provider windows, timestamps, percentages, and reset durations.
- Parse Codex rollout JSONL with malformed lines, incomplete tails, archived files, multiple sessions, and stale snapshots.
- Parse Claude plan-history samples and reject invalid sample shapes.
- Parse Antigravity quota messages, stale reset events, and log rotation.
- Validate account identity matching and profile path rules.
- Exercise cache TTL, stale fallback, provider-specific rate-limit handling, and error classification.

### Adapter tests

- Run Codex app-server behavior against a fake JSON-RPC subprocess fixture; cover initialization, account identity, live limits, login challenge, login completion, timeout, and mismatch.
- Mock Claude HTTP responses for success, 401, 429, malformed JSON, and missing windows.
- Use temporary files for Claude and Antigravity local artifacts.

### API tests

- Verify health and usage response shapes.
- Verify partial success when one account fails.
- Verify login routes do not return credentials.
- Verify unsupported login providers are rejected clearly.

### Local smoke test

After implementation, run the backend against the current machine’s configured profiles without changing account state. The smoke test should discover `wzf5350@gmail.com` for the existing Codex and Claude installations, return all four configured account records, and report the missing secondary Codex profile as not configured until the login flow is completed.

## Out of scope for this slice

- A web, TUI, or desktop frontend.
- Historical usage database or long-term analytics.
- Automatic Claude re-login that mutates the user’s browser/keychain state.
- Antigravity online API discovery beyond its local usage logs.
- Remote multi-user deployment, user authentication, or exposing login routes beyond localhost.
- Preserving the old Node/Vite or `/api/usage` interfaces.

## Acceptance criteria

The design is implemented when:

1. The repository runs from a clean `uv sync` environment with no Node runtime requirement.
2. Ruff and Ty pass, and provider/API tests pass.
3. `GET /v1/usage` always returns four configured account records with explicit freshness and error states.
4. The existing Codex profile retrieves live identity and rate limits through `codex app-server` when the provider is reachable.
5. The secondary Codex login flow can create its isolated profile, complete browser or device-code authentication, verify `wzf0513@gmail.com`, and make that profile eligible for live usage retrieval.
6. Claude returns live OAuth usage when a valid credential is available, otherwise a clearly labeled local fallback or authentication diagnostic.
7. Antigravity returns a normalized local-log result or a clearly labeled unavailable/stale diagnostic.
8. No API response, log line, committed file, or test fixture contains access tokens, refresh tokens, or raw credential content.
