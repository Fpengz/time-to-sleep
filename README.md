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
- Antigravity: `wzf5350@gmail.com` in `~/.config/Antigravity`

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

The second Codex account uses an isolated `CODEX_HOME`. Start a browser login:

```bash
curl -s -X POST http://127.0.0.1:4141/v1/accounts/codex-secondary/login/start \
  -H 'content-type: application/json' \
  -d '{"method":"browser"}'
```

For a device-code flow, send `{"method":"device_code"}` instead. The response
contains only the authorization URL, verification URL, user code, and attempt ID.
Poll the attempt and cancel it when needed:

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
  environment, macOS Keychain, or the configured credential file. When live OAuth
  usage is unavailable, it reads recent `plan-usage-history.json` data when present.
- Antigravity reads a bounded tail of its language-server log and reports the most
  recent quota reset event.

Provider credentials and tokens are never printed by the backend.
