# Python Usage Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Node/Vite monitor with a typed FastAPI backend that retrieves normalized usage for two Codex accounts, Claude, and Antigravity, including an isolated Codex login setup flow for the second account.

**Architecture:** A provider-neutral domain model and collection service sit behind FastAPI. Codex uses short-lived `codex app-server` JSON-RPC sessions for identity, live rate limits, and login; Claude uses an OAuth HTTP adapter with local history fallback; Antigravity uses a bounded local-log parser. Every result carries source, observation time, retrieval time, and freshness status, and failures are isolated per account.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, Pydantic Settings, HTTPX, uv, Ruff, Ty, pytest, pytest-asyncio, and respx.

---

## File map

Create the following focused modules:

- `pyproject.toml`: project metadata, dependencies, scripts, Ruff, and Ty settings.
- `config/accounts.toml`: four non-secret account definitions and isolated secondary Codex home.
- `src/time_to_sleep/domain.py`: immutable normalized models and error/status enums.
- `src/time_to_sleep/config.py`: settings and TOML account loading.
- `src/time_to_sleep/providers/base.py`: provider adapter protocol and shared result types.
- `src/time_to_sleep/providers/parsers.py`: pure local artifact parsers.
- `src/time_to_sleep/providers/codex.py`: app-server JSON-RPC client, rollout fallback, and Codex login session.
- `src/time_to_sleep/providers/claude.py`: Claude auth discovery, OAuth usage request, and plan-history fallback.
- `src/time_to_sleep/providers/antigravity.py`: language-server log reader.
- `src/time_to_sleep/services.py`: concurrent collection, cache policy, and login orchestration.
- `src/time_to_sleep/api.py`: FastAPI application and versioned routes.
- `src/time_to_sleep/__init__.py`: package marker and version.
- `src/time_to_sleep/__main__.py`: local Uvicorn entrypoint.
- `tests/conftest.py`: reusable account and temporary artifact fixtures.
- `tests/test_domain.py`: model and error normalization tests.
- `tests/test_config.py`: TOML configuration tests.
- `tests/test_parsers.py`: Codex, Claude, and Antigravity parser tests.
- `tests/test_codex.py`: fake app-server transport and Codex adapter tests.
- `tests/test_claude.py`: mocked Claude HTTP and local fallback tests.
- `tests/test_antigravity.py`: log adapter tests.
- `tests/test_services.py`: cache, timeout, partial-success, and login registry tests.
- `tests/test_api.py`: FastAPI contract tests.

The implementation removes `package.json`, `package-lock.json`, `server.mjs`, `accounts.json`, `vite.config.js`, `index.html`, `src/main.jsx`, `src/styles.css`, and the frontend-only public asset after the Python backend is working.

### Task 1: Bootstrap the uv Python project

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `config/accounts.toml`
- Create: `src/time_to_sleep/__init__.py`
- Create: `src/time_to_sleep/__main__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add the project metadata and tool configuration**

Create `pyproject.toml` with this shape:

```toml
[project]
name = "time-to-sleep"
version = "0.1.0"
description = "Local usage retrieval backend for coding agents"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115,<1",
  "httpx>=0.28,<1",
  "pydantic-settings>=2.7,<3",
  "uvicorn[standard]>=0.34,<1",
]

[dependency-groups]
dev = [
  "pytest>=8.3,<9",
  "pytest-asyncio>=0.25,<1",
  "respx>=0.22,<1",
  "ruff>=0.15,<1",
  "ty>=0.0.1,<1",
]

[project.scripts]
time-to-sleep = "time_to_sleep.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/time_to_sleep"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.ty.environment]
python-version = "3.12"
root = ["src"]
```

- [ ] **Step 2: Add the initial account configuration and package entrypoint**

Create `config/accounts.toml` with the four accounts from the approved design. Keep homes as `~/.codex`, `~/.config/time-to-sleep/accounts/codex-secondary`, `~/.claude`, and `~/.config/Antigravity`; do not include tokens.

Create `src/time_to_sleep/__init__.py` with `__version__ = "0.1.0"`.

Create `src/time_to_sleep/__main__.py`:

```python
import uvicorn


def main() -> None:
    uvicorn.run("time_to_sleep.api:app", host="127.0.0.1", port=4141, reload=False)


if __name__ == "__main__":
    main()
```

Create a minimal `README.md` containing the project name and the sentence `Operational commands are documented in the implementation-complete README.` so the declared project readme exists during bootstrap. Task 9 expands this file into the full operator guide.

- [ ] **Step 3: Install and verify the empty project**

Run:

```bash
uv sync
uv run ruff check .
uv run ty check
```

Expected: dependency resolution succeeds, Ruff reports no files with violations, and Ty reports no source files with errors. Commit:

```bash
git add pyproject.toml uv.lock config src tests/conftest.py
git commit -m "build: bootstrap Python backend"
```

### Task 2: Define domain models and typed configuration

**Files:**
- Create: `src/time_to_sleep/domain.py`
- Create: `src/time_to_sleep/config.py`
- Test: `tests/test_domain.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing model and configuration tests**

Add tests that require:

```python
from datetime import UTC, datetime

from time_to_sleep.config import load_settings
from time_to_sleep.domain import AccountConfig, AccountStatus, UsageSnapshot, UsageWindow


def test_usage_snapshot_preserves_missing_reset_and_freshness() -> None:
    snapshot = UsageSnapshot(
        account_id="claude",
        provider="claude",
        configured_email="wzf5350@gmail.com",
        status=AccountStatus.CACHED,
        source="claude_plan_history",
        observed_at=datetime(2026, 8, 18, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 18, 0, 1, tzinfo=UTC),
        windows=[UsageWindow(id="five_hour", used_percent=42.0, window_minutes=300)],
    )
    assert snapshot.windows[0].resets_at is None
    assert snapshot.status is AccountStatus.CACHED


def test_load_settings_reads_four_accounts(tmp_path) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        '[[accounts]]\nid = "codex"\nprovider = "codex"\n'
        'email = "a@example.com"\nhome = "~/.codex"\n',
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.accounts == [
        AccountConfig(id="codex", provider="codex", email="a@example.com", home="~/.codex")
    ]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run `uv run pytest tests/test_domain.py tests/test_config.py -q`.

Expected: collection fails because `time_to_sleep.domain` and `time_to_sleep.config` do not exist.

- [ ] **Step 3: Implement the models and loader**

Define `AccountStatus` as a string enum with `LIVE`, `CACHED`, `STALE`, and `UNAVAILABLE`, and `ErrorCode` as a string enum with `NOT_CONFIGURED`, `NOT_AUTHENTICATED`, `AUTHENTICATION_EXPIRED`, `RATE_LIMITED`, `PARSE_ERROR`, `TIMEOUT`, `IDENTITY_MISMATCH`, and `NO_RECENT_DATA`. Define Pydantic models `AccountConfig`, `UsageWindow`, `UsageSnapshot`, `LoginChallenge`, `LoginAttempt`, and `AccountStatusView` with timezone-aware datetimes, bounded `used_percent` from 0 through 100, optional reset timestamps, optional error codes, and optional diagnostics. `load_settings(path)` must parse TOML with `tomllib`, validate a non-empty unique account id, provider in `{codex, claude, antigravity}`, non-empty email/home, and return `Settings(accounts=...)`. Expand `~` only in a separate `AccountConfig.expanded_home` property so the serialized configuration remains portable.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```bash
uv run pytest tests/test_domain.py tests/test_config.py -q
uv run ruff check src/time_to_sleep/domain.py src/time_to_sleep/config.py tests/test_domain.py tests/test_config.py
uv run ty check
```

Expected: all focused tests pass and Ruff/Ty report no errors. Commit with `feat: add typed usage domain`.

### Task 3: Implement pure provider artifact parsers

**Files:**
- Create: `src/time_to_sleep/providers/__init__.py`
- Create: `src/time_to_sleep/providers/base.py`
- Create: `src/time_to_sleep/providers/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write parser tests before implementation**

Cover these exact inputs:

```python
def test_parse_codex_rollout_uses_newest_valid_rate_limit_event() -> None:
    lines = [
        '{"timestamp":"2026-08-18T00:00:00Z","payload":{"rate_limits":{"primary":{"used_percent":12,"window_minutes":300,"resets_at":1780000000}}}}',
        '{"timestamp":"2026-08-18T00:01:00Z","payload":{"rate_limits":{"primary":{"used_percent":25,"window_minutes":300,"resets_at":1780000300}}}}',
        "{bad json",
    ]
    result = parse_codex_rollout(lines)
    assert result.used_percent == 25
    assert result.window_minutes == 300


def test_parse_claude_plan_history_maps_fh_and_sd() -> None:
    result = parse_claude_plan_history(
        {"version": 2, "samples": [{"t": 1787000000000, "u": {"fh": 31, "sd": 44}}]}
    )
    assert [window.id for window in result.windows] == ["five_hour", "seven_day"]
    assert result.windows[1].used_percent == 44


def test_parse_antigravity_quota_event_calculates_reset() -> None:
    result = parse_antigravity_log(
        "2026-08-18T00:00:00Z Individual quota reached; Resets in 1h30m0s"
    )
    assert result.windows[0].used_percent == 100
    assert result.windows[0].window_minutes == 90
```

Also test empty input, out-of-range percentages, invalid timestamps, and stale Antigravity events.

- [ ] **Step 2: Run parser tests and verify they fail**

Run `uv run pytest tests/test_parsers.py -q`; expected failure is missing parser functions.

- [ ] **Step 3: Implement bounded, pure parsers**

Implement `parse_codex_rollout(lines: Iterable[str]) -> ParsedWindows`, `parse_claude_plan_history(document: Mapping[str, Any]) -> ParsedWindows`, and `parse_antigravity_log(content: str, now: datetime | None = None) -> ParsedWindows`. Use UTC timestamps, skip malformed JSONL lines, reject invalid numeric values, and never infer a reset timestamp that is absent from the source. `ParsedWindows` must include `observed_at`, a list of `UsageWindow`, and an optional source message.

- [ ] **Step 4: Run parser tests and commit**

Run `uv run pytest tests/test_parsers.py -q`; expected: all parser tests pass. Commit with `feat: add provider artifact parsers`.

### Task 4: Add the Codex app-server adapter and live identity checks

**Files:**
- Modify: `src/time_to_sleep/providers/base.py`
- Create: `src/time_to_sleep/providers/codex.py`
- Test: `tests/test_codex.py`

- [ ] **Step 1: Define a fake JSON-RPC transport and failing adapter tests**

Test the adapter with injected transport lines instead of the real network:

```python
async def test_codex_adapter_reads_identity_and_rate_limits(fake_codex_transport) -> None:
    adapter = CodexProvider(command="codex", transport_factory=fake_codex_transport)
    snapshot = await adapter.fetch(
        AccountConfig(id="codex", provider="codex", email="wzf5350@gmail.com", home="~/.codex")
    )
    assert snapshot.observed_email == "wzf5350@gmail.com"
    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.windows[0].used_percent == 15
```

Cover JSON-RPC initialization, `account/read`, `account/rateLimits/read`, process timeout, malformed response, missing executable, identity mismatch, and rollout fallback.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_codex.py -q`; expected: missing `CodexProvider` and transport implementation.

- [ ] **Step 3: Implement JSON-RPC process handling**

Implement an injected `CodexTransport` protocol with `request(method, params)`, `notify(method, params)`, and `close()`. The production transport starts `[command, "app-server", "--stdio"]` using `asyncio.create_subprocess_exec`, sets `CODEX_HOME` to `account.expanded_home`, writes one JSON object per line, reads response lines until the requested id arrives, ignores notifications, and kills the process on timeout. Use a unique numeric request id per transport.

`CodexProvider.fetch` must:

1. Call `initialize` with client metadata `{name: "time_to_sleep", title: "Time-to-Sleep", version: __version__}`.
2. Send the `initialized` notification.
3. Call `account/read` with `refreshToken: false`.
4. Call `account/rateLimits/read`.
5. Compare reported email with `AccountConfig.email`.
6. Normalize `rateLimits.primary`, `rateLimits.secondary`, and any `rateLimitsByLimitId` windows without fabricating missing windows.
7. On live failure, scan the most recent bounded Codex rollout files under `home/sessions` and `home/archived_sessions` with `parse_codex_rollout` and return cached/stale data with the original error category.

- [ ] **Step 4: Run tests, Ty, and commit**

Run `uv run pytest tests/test_codex.py -q && uv run ty check`; expected: all Codex tests and type checks pass. Commit with `feat: retrieve Codex usage through app-server`.

### Task 5: Add Claude OAuth and Antigravity log adapters

**Files:**
- Create: `src/time_to_sleep/providers/claude.py`
- Create: `src/time_to_sleep/providers/antigravity.py`
- Test: `tests/test_claude.py`
- Test: `tests/test_antigravity.py`

- [ ] **Step 1: Write failing Claude and Antigravity tests**

Mock Claude success, 401, 429, malformed JSON, and missing-window responses with `respx`. Test credential extraction from a mapping, not raw token output. Test the local plan-history fallback and Antigravity fresh/stale log behavior.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_claude.py tests/test_antigravity.py -q`; expected: missing provider classes.

- [ ] **Step 3: Implement Claude provider**

Implement `ClaudeCredentialSource` with this precedence: `CLAUDE_CODE_OAUTH_TOKEN`, macOS `security find-generic-password -s Claude Code-credentials -a <user> -w`, then `<home>/.credentials.json`. Parse only `.claudeAiOauth.accessToken`. Never log or return the token.

Implement `ClaudeProvider.fetch` using `httpx.AsyncClient` with a 10-second timeout, `Authorization: Bearer`, and `anthropic-beta: oauth-2025-04-20` against `https://api.anthropic.com/api/oauth/usage`. Map `five_hour` and `seven_day` fields to `UsageWindow`; classify 401 as `authentication_expired` and 429 as `rate_limited`. On any live failure, search `<home>/plan-usage-history.json` and macOS Claude Desktop’s application-support path, parse the latest sample, and return `cached` or `stale` based on its age.

- [ ] **Step 4: Implement Antigravity provider**

Implement `AntigravityProvider.fetch` to read only a bounded tail of `<home>/logs/language_server.log`, call `parse_antigravity_log`, and return `unavailable` with `no_recent_data` when no valid non-expired quota event exists. Do not treat a missing log as a process-level error.

- [ ] **Step 5: Run provider tests and commit**

Run:

```bash
uv run pytest tests/test_claude.py tests/test_antigravity.py -q
uv run ruff check .
uv run ty check
```

Expected: tests and static checks pass. Commit with `feat: add Claude and Antigravity usage adapters`.

### Task 6: Add collection service, cache policy, and error isolation

**Files:**
- Create: `src/time_to_sleep/services.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Write failing service tests**

Test that four account adapters run independently, one exception produces one `unavailable` snapshot, cached values are reused within TTL, Claude live calls are not repeated inside its five-minute TTL, and an expired cache is marked `stale` rather than returned as `live`.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_services.py -q`; expected: missing collection service.

- [ ] **Step 3: Implement service boundaries**

Define `ProviderRegistry`, `UsageCache`, and `UsageService`:

```python
class UsageService:
    async def collect(self, *, force_refresh: bool = False) -> list[UsageSnapshot]: ...
    async def account_status(self, account_id: str) -> AccountStatusView: ...
```

Use `asyncio.gather(..., return_exceptions=True)` with a per-provider timeout. Use 60 seconds for Codex, 300 seconds for Claude live OAuth, and direct local reads for Antigravity and local fallbacks. On a live error, return the last successful snapshot with `status` changed to `cached` or `stale` and attach the categorized message. A failed account must never cancel sibling collections.

- [ ] **Step 4: Run service tests and commit**

Run `uv run pytest tests/test_services.py -q`; expected: all service tests pass. Commit with `feat: add resilient usage collection service`.

### Task 7: Implement Codex login attempt orchestration

**Files:**
- Modify: `src/time_to_sleep/providers/codex.py`
- Modify: `src/time_to_sleep/services.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Write failing login tests**

Cover browser and device-code challenges, pending status, completion with the expected email, identity mismatch, cancellation, timeout cleanup, and rejection for non-Codex accounts.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_services.py -k login -q`; expected: missing login orchestration methods.

- [ ] **Step 3: Implement login registry**

Add `LoginService.start(account_id, method)`, `status(account_id, attempt_id)`, and `cancel(account_id, attempt_id)`. Allow only `browser` and `device_code`, mapping them to Codex `account/login/start` types `chatgpt` and `chatgptDeviceCode` respectively. Create the configured profile directory with mode `0700`, start an isolated Codex app-server, send the login request, and return a `LoginChallenge` containing only URL/code fields. A background task waits for `account/login/completed`, then verifies `account/read` email before marking success. Close and kill the process in every terminal state. Expire attempts after 10 minutes.

- [ ] **Step 4: Run login tests and commit**

Run `uv run pytest tests/test_services.py -k login -q && uv run ty check`; expected: all login tests pass. Commit with `feat: add isolated Codex login flow`.

### Task 8: Expose the FastAPI contract

**Files:**
- Create: `src/time_to_sleep/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API contract tests**

Use `fastapi.testclient.TestClient` with dependency overrides. Assert:

```python
def test_usage_returns_all_account_records(client):
    response = client.get("/v1/usage")
    assert response.status_code == 200
    body = response.json()
    assert len(body["accounts"]) == 4
    assert {account["status"] for account in body["accounts"]} <= {
        "live",
        "cached",
        "stale",
        "unavailable",
    }
```

Also test `/health`, `/v1/accounts`, `force_refresh`, login start/status/cancel, unsupported provider login, and error responses without secrets.

- [ ] **Step 2: Run API tests and verify failure**

Run `uv run pytest tests/test_api.py -q`; expected: missing `time_to_sleep.api:app` and routes.

- [ ] **Step 3: Implement FastAPI routes**

Create `app = FastAPI(title="Time-to-Sleep Usage Backend", version=__version__)`. Bind routes:

- `GET /health` returns `{status: "ok", configured_accounts: n}`.
- `GET /v1/accounts` returns typed account status views.
- `GET /v1/usage?force_refresh=false` returns `{generated_at, accounts}`.
- `POST /v1/accounts/{account_id}/login/start` accepts `{"method":"browser"|"device_code"}` and returns 202 with challenge data.
- `GET /v1/accounts/{account_id}/login/{attempt_id}` returns login state.
- `POST /v1/accounts/{account_id}/login/{attempt_id}/cancel` returns the cancelled state.

Use HTTP 404 for unknown account/attempt, 409 for account/provider state conflicts, 422 for invalid login method, and 200 for aggregate usage even when individual accounts are unavailable. Wire dependencies from settings and services so tests can replace them.

- [ ] **Step 4: Run API tests and commit**

Run `uv run pytest tests/test_api.py -q && uv run ruff check . && uv run ty check`; expected: all pass. Commit with `feat: expose FastAPI usage API`.

### Task 9: Remove the old runtime and add operational documentation

**Files:**
- Modify: `README.md`
- Delete: `package.json`
- Delete: `package-lock.json`
- Delete: `server.mjs`
- Delete: `accounts.json`
- Delete: `vite.config.js`
- Delete: `index.html`
- Delete: `src/main.jsx`
- Delete: `src/styles.css`
- Delete: `public/agent-archipelago.png`

- [ ] **Step 1: Write the backend README**

Document `uv sync`, `uv run time-to-sleep`, `uv run uvicorn time_to_sleep.api:app --reload`, `uv run pytest`, `uv run ruff format --check .`, `uv run ruff check .`, and `uv run ty check`. Document that the server is loopback-only, how to start the second Codex browser/device login through the API, how to set `TIME_TO_SLEEP_CONFIG`, and that provider credentials remain managed by Codex/Claude rather than committed.

- [ ] **Step 2: Remove obsolete Node/Vite files**

Delete text files with `apply_patch` and remove the binary public asset with `git rm`. Do not add a compatibility server or preserve the old `/api/usage` route.

- [ ] **Step 3: Run the complete suite and migration checks**

Run:

```bash
uv sync
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run python -m time_to_sleep
```

For the last command, stop it after confirming Uvicorn binds to `127.0.0.1:4141`, then run `curl -s http://127.0.0.1:4141/health` and `curl -s http://127.0.0.1:4141/v1/usage` against the local configuration. Confirm the response contains four records, the existing Codex identity is `wzf5350@gmail.com`, and the secondary Codex is explicitly not configured until its login flow completes. Commit with `chore: remove Node frontend runtime`.

### Task 10: Final verification and handoff

**Files:**
- Modify: any files required by failing checks from Tasks 1–9

- [ ] **Step 1: Run the verification matrix**

Run `uv run pytest`, `uv run ruff format --check .`, `uv run ruff check .`, and `uv run ty check` from a clean working tree.

- [ ] **Step 2: Run a no-secret scan**

Run `rg -n -i 'access[_-]?token|refresh[_-]?token|authorization: bearer|api[_-]?key|secret' src tests config README.md` and inspect that only field names, redaction logic, or non-secret documentation examples appear; no credential values may be present.

- [ ] **Step 3: Review the diff and commit any verification fixes**

Run `git diff --check`, `git status --short`, and `git diff --stat`. Fix only issues in scope, rerun the full verification matrix, and commit the final fix with a focused message.
