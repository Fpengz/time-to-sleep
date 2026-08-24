from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from time_to_sleep.cli import format_prompt, format_table, main
from time_to_sleep.domain import AccountStatus, UsageSnapshot, UsageWindow


def test_format_table() -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    snapshot = UsageSnapshot(
        account_id="codex-primary",
        provider="codex",
        configured_email="test@example.com",
        status=AccountStatus.LIVE,
        source="app-server",
        retrieved_at=now,
        windows=[UsageWindow(id="primary", used_percent=65.5, resets_at=now)],
    )

    table = format_table([snapshot])
    assert "Codex" in table
    assert "codex-primary" in table
    assert "65.5%" in table
    assert "LIVE" in table


def test_format_prompt() -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    snapshots = [
        UsageSnapshot(
            account_id="codex-primary",
            provider="codex",
            configured_email="test@example.com",
            status=AccountStatus.LIVE,
            source="app-server",
            retrieved_at=now,
            windows=[UsageWindow(id="primary", used_percent=60.0)],
        ),
        UsageSnapshot(
            account_id="claude-primary",
            provider="claude",
            configured_email="test@example.com",
            status=AccountStatus.RATE_LIMITED,
            source="oauth",
            retrieved_at=now,
        ),
    ]

    prompt = format_prompt(snapshots, format_type="compact")
    assert prompt == "[Codex:60% | Claude:!]"

    prompt_json = format_prompt(snapshots, format_type="json")
    assert '"max_used_percent": 60.0' in prompt_json
    assert '"needs_attention": true' in prompt_json

    prompt_sketchy = format_prompt(snapshots, format_type="sketchybar")
    assert "Codex:60% | Claude:!" in prompt_sketchy

    prompt_waybar = format_prompt(snapshots, format_type="waybar")
    assert '"percentage": 60' in prompt_waybar
    assert '"class": "normal"' in prompt_waybar


@patch("time_to_sleep.cli.fetch_usage", new_callable=AsyncMock)
def test_cli_main_status(mock_fetch: AsyncMock, capsys: object) -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    mock_fetch.return_value = [
        UsageSnapshot(
            account_id="codex-primary",
            provider="codex",
            configured_email="test@example.com",
            status=AccountStatus.LIVE,
            source="app-server",
            retrieved_at=now,
            windows=[UsageWindow(id="primary", used_percent=20.0)],
        )
    ]

    main(["status"])
    captured = capsys.readouterr()  # type: ignore
    assert "Codex" in captured.out
    assert "20.0%" in captured.out


def test_cli_discover(capsys: object) -> None:
    main(["discover", "--json"])
    captured = capsys.readouterr()  # type: ignore
    assert "[" in captured.out
