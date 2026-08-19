# Time-to-Sleep

Local FastAPI backend for retrieving normalized usage from Codex, Claude Code, and
Antigravity. The backend is intentionally loopback-only and does not expose the old
Node/Vite runtime or `/api/usage` compatibility route.

## Development

```bash
uv sync
uv run time-to-sleep
```

The default server listens on `127.0.0.1:4141`. For development with reload:

```bash
uv run uvicorn time_to_sleep.api:app --reload
```

Open the dashboard at <http://127.0.0.1:4141/>. The interactive API reference is
available at <http://127.0.0.1:4141/docs>. The theme follows the operating system
on first load; use the header toggle to persist an explicit light or dark choice.

Run the verification commands with:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run playwright install chromium
uv run python tests/browser_dashboard.py
```

## Configuration

Account definitions live in `config/accounts.toml`. Override the file with:

```bash
TIME_TO_SLEEP_CONFIG=/path/to/accounts.toml uv run time-to-sleep
```

The configuration contains account IDs, provider names, emails, and local profile
homes only. Credentials are never committed. Codex and Claude credentials remain
managed by their own CLIs and operating-system credential stores.

The configured accounts are:

- Codex: `wzf5350@gmail.com` in `~/.codex`
- Codex: `wzf0513@gmail.com` in an isolated profile under
  `~/.config/time-to-sleep/accounts/codex-secondary`
- Claude Code: `wzf5350@gmail.com` in `~/.claude`
- Antigravity: `wzf5350@gmail.com` through the local `agy`/Antigravity server

## API

```bash
curl -s http://127.0.0.1:4141/health
curl -s http://127.0.0.1:4141/v1/accounts
curl -s http://127.0.0.1:4141/v1/usage
curl -s 'http://127.0.0.1:4141/v1/usage?force_refresh=true'
```

`/v1/usage` returns one normalized record per configured account, even when a
provider is unavailable. Each record includes its status, source, observation time,
retrieval time, windows, and diagnostic error code when applicable.

## Codex login setup

The second Codex account uses an isolated `CODEX_HOME`. The dashboard defaults to
device-code login so it can authenticate `wzf0513@gmail.com` independently of the
primary browser session:

```bash
curl -s -X POST http://127.0.0.1:4141/v1/accounts/codex-secondary/login/start \
  -H 'content-type: application/json' \
  -d '{"method":"device_code"}'
```

Open the returned verification URL, sign in as `wzf0513@gmail.com`, and enter the
returned user code. If using browser login instead, use a private window or sign
out of the primary ChatGPT account first; otherwise the login may complete for
`wzf5350@gmail.com` and be rejected. The response contains the authorization URL,
verification URL, user code, and attempt ID. Poll the attempt and cancel it when
needed:

```bash
curl -s http://127.0.0.1:4141/v1/accounts/codex-secondary/login/<attempt_id>
curl -s -X POST http://127.0.0.1:4141/v1/accounts/codex-secondary/login/<attempt_id>/cancel
```

The service verifies that the completed Codex session belongs to
`wzf0513@gmail.com` before reporting success. Attempts expire after ten minutes and
their app-server process is closed in every terminal state.

## Provider retrieval notes

- Codex uses short-lived `codex app-server --stdio` JSON-RPC sessions for identity
  and live rate limits, with recent rollout data as a bounded fallback.
- Claude first tries the OAuth usage endpoint using credentials discovered from the
  environment, macOS Keychain, or the configured credential file. If Anthropic
  rate-limits that endpoint, the provider reports `rate_limited`, honors the
  server-provided retry window, and never presents stale history as current usage.
  An optional web-session source can be enabled with `CLAUDE_WEB_ORGANIZATION_ID`
  and `CLAUDE_WEB_SESSION_KEY` (or `CLAUDE_WEB_COOKIE`). Keep the session value in
  the process environment only; do not commit it. Recent
  `plan-usage-history.json` data remains a bounded fallback.
- Antigravity discovers the local app or `agy` language server, starts `agy` when
  needed, and reads its `RetrieveUserQuotaSummary` response for the Gemini and
  Claude/GPT shared pools. It verifies the returned Google account before showing
  usage and cleans up any temporary CLI process it started.

Provider credentials and tokens are never printed by the backend.
