from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode
from time_to_sleep.providers.claude import ClaudeCredentialSource, ClaudeProvider


def account(home: str) -> AccountConfig:
    return AccountConfig(id="claude", provider="claude", email="wzf5350@gmail.com", home=home)


def test_credential_source_extracts_nested_oauth_token(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    source = ClaudeCredentialSource(
        home=Path("/tmp/no-claude-home"),
        keychain_loader=lambda: '{"claudeAiOauth":{"accessToken":"secret-token"}}',
    )

    assert source.get_token() == "secret-token"


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

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.RATE_LIMITED
    assert snapshot.windows == []
