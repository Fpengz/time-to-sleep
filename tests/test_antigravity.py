from datetime import UTC, datetime
from pathlib import Path

import pytest

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode
from time_to_sleep.providers.antigravity import AntigravityProvider


def account(home: str) -> AccountConfig:
    return AccountConfig(
        id="antigravity", provider="antigravity", email="wzf5350@gmail.com", home=home
    )


@pytest.mark.asyncio
async def test_antigravity_provider_reads_recent_quota_log(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "language_server.log"
    log.parent.mkdir()
    log.write_text(
        "2026-08-18T00:00:00Z Individual quota reached; Resets in 1h30m0s\n",
        encoding="utf-8",
    )

    snapshot = await AntigravityProvider(
        now=lambda: datetime(2026, 8, 18, 0, 10, tzinfo=UTC)
    ).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.windows[0].used_percent == 100
    assert snapshot.windows[0].window_minutes == 90


@pytest.mark.asyncio
async def test_antigravity_provider_reports_missing_log_without_data(tmp_path: Path) -> None:
    snapshot = await AntigravityProvider().fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.NOT_CONFIGURED
