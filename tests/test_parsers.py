from datetime import UTC, datetime

import pytest

from time_to_sleep.providers.parsers import (
    parse_antigravity_log,
    parse_antigravity_quota_summary,
    parse_claude_plan_history,
    parse_codex_rollout,
)


def test_parse_codex_rollout_uses_newest_valid_rate_limit_event() -> None:
    lines = [
        '{"timestamp":"2026-08-18T00:00:00Z","payload":{"rate_limits":{"primary":{"used_percent":12,"window_minutes":300,"resets_at":1780000000}}}}',
        '{"timestamp":"2026-08-18T00:01:00Z","payload":{"rate_limits":{"primary":{"used_percent":25,"window_minutes":300,"resets_at":1780000300}}}}',
        "{bad json",
    ]

    result = parse_codex_rollout(lines)

    assert result.windows[0].used_percent == 25
    assert result.windows[0].window_minutes == 300


def test_parse_codex_rollout_maps_primary_and_secondary_windows() -> None:
    result = parse_codex_rollout(
        [
            '{"timestamp":"2026-08-18T00:00:00Z","payload":{"rate_limits":{'
            '"primary":{"used_percent":12,"window_minutes":300,"resets_at":1780000000},'
            '"secondary":{"used_percent":44,"window_minutes":10080,"resets_at":1780604800}'
            "}}}"
        ]
    )

    assert [window.id for window in result.windows] == ["primary", "secondary"]


def test_parse_claude_plan_history_maps_fh_and_sd() -> None:
    result = parse_claude_plan_history(
        {"version": 2, "samples": [{"t": 1787000000000, "u": {"fh": 31, "sd": 44}}]}
    )

    assert [window.id for window in result.windows] == ["five_hour", "seven_day"]
    assert result.windows[1].used_percent == 44


def test_parse_claude_plan_history_rejects_invalid_sample() -> None:
    with pytest.raises(ValueError, match="valid samples"):
        parse_claude_plan_history({"version": 2, "samples": [{"t": "bad", "u": {}}]})


def test_parse_antigravity_quota_event_calculates_reset() -> None:
    result = parse_antigravity_log(
        "2026-08-18T00:00:00Z Individual quota reached; Resets in 1h30m0s",
        now=datetime(2026, 8, 18, 0, 10, tzinfo=UTC),
    )

    assert result.windows[0].used_percent == 100
    assert result.windows[0].window_minutes == 90
    assert result.windows[0].resets_at == datetime(2026, 8, 18, 1, 30, tzinfo=UTC)


def test_parse_antigravity_log_rejects_stale_quota_event() -> None:
    with pytest.raises(ValueError, match="stale"):
        parse_antigravity_log(
            "2026-08-17T00:00:00Z Individual quota reached; Resets in 1h0m0s",
            now=datetime(2026, 8, 18, 0, 10, tzinfo=UTC),
        )


def test_parse_antigravity_quota_summary_maps_shared_pools() -> None:
    result = parse_antigravity_quota_summary(
        {
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "bucketId": "gemini-weekly",
                                "remainingFraction": 0.75,
                                "resetTime": "2026-08-24T12:00:00Z",
                            },
                            {
                                "bucketId": "gemini-5h",
                                "remainingFraction": 1,
                                "resetTime": "2026-08-19T07:00:00Z",
                            },
                        ],
                    },
                    {
                        "displayName": "Claude and GPT models",
                        "buckets": [
                            {
                                "bucketId": "3p-weekly",
                                "remainingFraction": 0.5,
                                "resetTime": "2026-08-26T02:00:00Z",
                            }
                        ],
                    },
                ]
            }
        },
        now=datetime(2026, 8, 19, 1, tzinfo=UTC),
    )

    assert [window.id for window in result.windows] == [
        "gemini_weekly",
        "gemini_five_hour",
        "third_party_weekly",
    ]
    assert result.windows[0].used_percent == 25
    assert result.windows[0].window_minutes == 10080
    assert result.windows[1].window_minutes == 300
    assert result.windows[2].used_percent == 50
