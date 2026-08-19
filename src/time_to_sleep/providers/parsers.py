import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from time_to_sleep.domain import UsageWindow
from time_to_sleep.providers.base import ParsedWindows


def _timestamp(value: Any, *, milliseconds: bool = False) -> datetime:
    if not isinstance(value, (int, float, str)):
        raise ValueError("timestamp is invalid")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / (1000 if milliseconds else 1), tz=UTC)
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _percent(value: Any) -> float:
    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
        raise ValueError("usage percentage is invalid")
    return float(value)


def _window(window_id: str, raw: Mapping[str, Any]) -> UsageWindow:
    used = raw.get("used_percent", raw.get("usedPercent"))
    duration = raw.get("window_minutes", raw.get("windowDurationMins"))
    reset = raw.get("resets_at", raw.get("resetsAt"))
    return UsageWindow(
        id=window_id,
        used_percent=_percent(used),
        window_minutes=int(duration) if duration is not None else None,
        resets_at=_timestamp(reset) if reset is not None else None,
    )


def parse_codex_rollout(lines: Iterable[str]) -> ParsedWindows:
    newest: tuple[datetime, Mapping[str, Any]] | None = None
    for line in lines:
        try:
            event = json.loads(line)
            timestamp = _timestamp(event.get("timestamp"))
            raw_limits = event.get("payload", {}).get("rate_limits")
            if not isinstance(raw_limits, Mapping):
                continue
            windows = {
                key: value
                for key, value in raw_limits.items()
                if key in {"primary", "secondary"} and isinstance(value, Mapping)
            }
            if windows and (newest is None or timestamp > newest[0]):
                newest = timestamp, windows
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

    if newest is None:
        raise ValueError("no valid Codex rate limit event found")
    timestamp, raw_windows = newest
    return ParsedWindows(
        observed_at=timestamp,
        windows=[_window(window_id, raw) for window_id, raw in raw_windows.items()],
    )


def parse_claude_plan_history(document: Mapping[str, Any]) -> ParsedWindows:
    samples = document.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Claude plan history has no valid samples")

    valid_samples: list[tuple[datetime, Mapping[str, Any]]] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        try:
            timestamp = _timestamp(sample["t"], milliseconds=True)
            usage = sample["u"]
            if not isinstance(usage, Mapping):
                continue
            valid_samples.append((timestamp, usage))
        except (KeyError, TypeError, ValueError):
            continue

    if not valid_samples:
        raise ValueError("Claude plan history has no valid samples")
    observed_at, usage = max(valid_samples, key=lambda item: item[0])
    windows = []
    for window_id, source_key, duration in (
        ("five_hour", "fh", 300),
        ("seven_day", "sd", 10080),
    ):
        if source_key in usage:
            windows.append(
                UsageWindow(
                    id=window_id,
                    used_percent=_percent(usage[source_key]),
                    window_minutes=duration,
                )
            )
    if not windows:
        raise ValueError("Claude plan history has no valid usage windows")
    return ParsedWindows(observed_at=observed_at, windows=windows)


_ANTIGRAVITY_EVENT = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}(?:T| )\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z)?)"
    r"[\s\S]{0,240}?Individual quota reached[\s\S]{0,160}?"
    r"Resets in (?P<hours>\d+)h(?P<minutes>\d+)m(?P<seconds>\d+)s",
    re.IGNORECASE,
)


def parse_antigravity_log(content: str, now: datetime | None = None) -> ParsedWindows:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    matches = list(_ANTIGRAVITY_EVENT.finditer(content))
    if not matches:
        raise ValueError("no Antigravity quota event found")

    latest = matches[-1]
    observed_at = _timestamp(latest.group("timestamp"))
    duration = timedelta(
        hours=int(latest.group("hours")),
        minutes=int(latest.group("minutes")),
        seconds=int(latest.group("seconds")),
    )
    resets_at = observed_at + duration
    if resets_at <= current:
        raise ValueError("Antigravity quota event is stale")
    return ParsedWindows(
        observed_at=observed_at,
        windows=[
            UsageWindow(
                id="quota-event",
                used_percent=100,
                window_minutes=max(1, round(duration.total_seconds() / 60)),
                resets_at=resets_at,
            )
        ],
    )


def parse_antigravity_quota_summary(
    document: Mapping[str, Any], now: datetime | None = None
) -> ParsedWindows:
    response = document.get("response", document)
    if not isinstance(response, Mapping):
        raise ValueError("Antigravity quota summary response is not an object")
    groups = response.get("groups")
    if not isinstance(groups, list):
        raise ValueError("Antigravity quota summary has no groups")

    windows: list[UsageWindow] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        group_name = str(group.get("displayName", "")).lower()
        group_id = "gemini" if "gemini" in group_name else "third_party"
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue
        for bucket in buckets:
            if not isinstance(bucket, Mapping):
                continue
            remaining = bucket.get("remainingFraction")
            if not isinstance(remaining, (int, float)) or not 0 <= float(remaining) <= 1:
                continue
            bucket_id = str(bucket.get("bucketId", "")).lower()
            window_kind = str(bucket.get("window", "")).lower()
            if "weekly" in bucket_id or window_kind == "weekly":
                suffix = "weekly"
                duration = 10080
            elif "5h" in bucket_id or window_kind in {"5h", "five_hour", "five-hour"}:
                suffix = "five_hour"
                duration = 300
            else:
                suffix = bucket_id.replace("-", "_") or "unknown"
                duration = None
            reset = bucket.get("resetTime")
            try:
                resets_at = _timestamp(reset) if reset is not None else None
            except ValueError:
                resets_at = None
            windows.append(
                UsageWindow(
                    id=f"{group_id}_{suffix}",
                    used_percent=round((1 - float(remaining)) * 100, 4),
                    window_minutes=duration,
                    resets_at=resets_at,
                )
            )

    if not windows:
        raise ValueError("Antigravity quota summary has no valid buckets")
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    return ParsedWindows(observed_at=observed_at, windows=windows)
