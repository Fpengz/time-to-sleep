from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode
from time_to_sleep.providers.claude import (
    CLAUDE_WEB_USAGE_URL,
    ClaudeCredentialSource,
    ClaudeProvider,
)


def account(home: str) -> AccountConfig:
    return AccountConfig(id="claude", provider="claude", email="wzf5350@gmail.com", home=home)


def test_credential_source_extracts_nested_oauth_token(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    source = ClaudeCredentialSource(
        home=Path("/tmp/no-claude-home"),
        keychain_loader=lambda: '{"claudeAiOauth":{"accessToken":"test-oauth-value"}}',
    )

    assert source.get_token() == "test-oauth-value"


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_returns_live_oauth_usage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(
            200,
            json={
                "five_hour": {"utilization": 23.5, "resets_at": 1788422400},
                "seven_day": {"utilization": 41.2, "resets_at": 1788940800},
            },
        )
    )

    snapshot = await ClaudeProvider().fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.source == "claude_oauth"
    assert [window.used_percent for window in snapshot.windows] == [23.5, 41.2]
    assert snapshot.windows[0].resets_at == datetime.fromtimestamp(1788422400, tz=UTC)


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_uses_web_usage_when_oauth_is_rate_limited(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    web_usage = {
        "five_hour": {"utilization": 18.0, "resets_at": "2026-08-19T04:00:00Z"},
        "seven_day": {"utilization": 36.5, "resets_at": "2026-08-24T00:00:00Z"},
    }

    async def fetch_web_usage(_account: AccountConfig) -> dict[str, Any]:
        return web_usage

    snapshot = await ClaudeProvider(
        include_desktop_history=False,
        web_usage_fetcher=fetch_web_usage,
    ).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.source == "claude_web"
    assert snapshot.error_code is None
    assert [window.used_percent for window in snapshot.windows] == [18.0, 36.5]


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_uses_configured_web_session(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    monkeypatch.setenv("CLAUDE_WEB_ORGANIZATION_ID", "org-123")
    monkeypatch.setenv("CLAUDE_WEB_SESSION_KEY", "session-value")
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "60"})
    )
    web_route = respx.get(CLAUDE_WEB_USAGE_URL.format(organization_id="org-123")).mock(
        return_value=httpx.Response(
            200,
            json={"five_hour": {"utilization": 12}, "seven_day": {"utilization": 27}},
        )
    )

    snapshot = await ClaudeProvider(include_desktop_history=False).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.source == "claude_web"
    assert web_route.calls.last.request.headers["Cookie"] == "sessionKey=session-value"


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_uses_plan_history_after_expired_oauth(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "expired-token")
    observed_at = int(datetime.now(UTC).timestamp() * 1000)
    (tmp_path / "plan-usage-history.json").write_text(
        f'{{"version":2,"samples":[{{"t":{observed_at},"u":{{"fh":31,"sd":44}}}}]}}',
        encoding="utf-8",
    )
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(401, json={"error": {"message": "expired"}})
    )

    snapshot = await ClaudeProvider(include_desktop_history=False).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.CACHED
    assert snapshot.source == "claude_plan_history"
    assert snapshot.error_code is ErrorCode.AUTHENTICATION_EXPIRED
    assert [window.used_percent for window in snapshot.windows] == [31, 44]


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_classifies_rate_limit_without_fabricating_usage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )

    snapshot = await ClaudeProvider(include_desktop_history=False).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.RATE_LIMITED
    assert snapshot.error_code is ErrorCode.RATE_LIMITED
    assert snapshot.windows == []


@pytest.mark.asyncio
@respx.mock
async def test_claude_provider_does_not_present_old_history_as_current_usage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    observed_at = int((datetime.now(UTC) - timedelta(days=2)).timestamp() * 1000)
    (tmp_path / "plan-usage-history.json").write_text(
        f'{{"version":2,"samples":[{{"t":{observed_at},"u":{{"fh":51,"sd":25}}}}]}}',
        encoding="utf-8",
    )
    respx.get("https://api.anthropic.com/api/oauth/usage").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )

    snapshot = await ClaudeProvider(include_desktop_history=False).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.RATE_LIMITED
    assert snapshot.source == "claude_plan_history"
    assert snapshot.error_code is ErrorCode.RATE_LIMITED
    assert snapshot.windows == []
    assert "stale" in (snapshot.message or "").lower()
