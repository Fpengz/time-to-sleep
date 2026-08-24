from datetime import UTC, datetime
from pathlib import Path

import pytest

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode
from time_to_sleep.providers.antigravity import AntigravityProvider, AntigravitySourceError


def account(home: str) -> AccountConfig:
    return AccountConfig(
        id="antigravity", provider="antigravity", email="wzf5350@gmail.com", home=home
    )


@pytest.mark.asyncio
async def test_antigravity_provider_reports_missing_log_without_data(tmp_path: Path) -> None:
    async def source(_: AccountConfig) -> tuple[dict[str, object], None, str]:
        raise AntigravitySourceError(ErrorCode.NOT_CONFIGURED, "Antigravity CLI is not installed")

    snapshot = await AntigravityProvider(source=source).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.NOT_CONFIGURED


@pytest.mark.asyncio
async def test_antigravity_provider_reads_cli_quota_summary_and_identity() -> None:
    async def source(_: AccountConfig) -> tuple[dict[str, object], dict[str, object], str]:
        return (
            {
                "response": {
                    "groups": [
                        {
                            "displayName": "Gemini Models",
                            "buckets": [
                                {
                                    "bucketId": "gemini-weekly",
                                    "remainingFraction": 0.8,
                                    "resetTime": "2026-08-24T12:00:00Z",
                                }
                            ],
                        }
                    ]
                }
            },
            {
                "userStatus": {
                    "email": "wzf5350@gmail.com",
                    "userTier": {"name": "Google AI Pro"},
                }
            },
            "antigravity_cli",
        )

    snapshot = await AntigravityProvider(
        now=lambda: datetime(2026, 8, 19, 1, tzinfo=UTC),
        source=source,
    ).fetch(account("/unused"))

    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.source == "antigravity_cli"
    assert snapshot.observed_email == "wzf5350@gmail.com"
    assert snapshot.plan_type == "Google AI Pro"
    assert snapshot.windows[0].used_percent == 20


@pytest.mark.asyncio
async def test_antigravity_provider_rejects_wrong_authenticated_account() -> None:
    async def source(_: AccountConfig) -> tuple[dict[str, object], dict[str, object], str]:
        return ({"response": {"groups": []}}, {"userStatus": {"email": "other@example.com"}}, "cli")

    snapshot = await AntigravityProvider(source=source).fetch(account("/unused"))

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.IDENTITY_MISMATCH
    assert snapshot.observed_email == "other@example.com"


@pytest.mark.asyncio
async def test_antigravity_provider_surfaces_missing_cli_auth() -> None:
    async def source(_: AccountConfig) -> tuple[dict[str, object], dict[str, object], str]:
        raise AntigravitySourceError(ErrorCode.NOT_AUTHENTICATED, "Run agy and sign in first")

    snapshot = await AntigravityProvider(source=source).fetch(account("/unused"))

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.NOT_AUTHENTICATED
    assert snapshot.message == "Run agy and sign in first"
