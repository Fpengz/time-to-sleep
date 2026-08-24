from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def test_usage_window_rejects_percentages_outside_provider_range() -> None:
    with pytest.raises(ValidationError):
        UsageWindow(id="five_hour", used_percent=101, window_minutes=300)


def test_account_config_expands_home_without_changing_serialized_home(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")
    account = AccountConfig(id="codex", provider="codex", email="a@example.com", home="~/.codex")

    assert account.home == "~/.codex"
    assert account.expanded_home == "/tmp/example-home/.codex"
