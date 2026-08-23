from datetime import UTC, datetime, timedelta

from time_to_sleep.domain import AccountStatus, UsageSnapshot, UsageWindow
from time_to_sleep.history import HistoryStore


def test_history_store_record_and_query() -> None:
    store = HistoryStore(":memory:")
    now = datetime.now(UTC)

    snap1 = UsageSnapshot(
        account_id="codex-primary",
        provider="codex",
        configured_email="test@example.com",
        status=AccountStatus.LIVE,
        source="test",
        retrieved_at=now - timedelta(minutes=10),
        windows=[UsageWindow(id="primary", used_percent=45.0)],
    )

    snap2 = UsageSnapshot(
        account_id="codex-primary",
        provider="codex",
        configured_email="test@example.com",
        status=AccountStatus.LIVE,
        source="test",
        retrieved_at=now,
        windows=[UsageWindow(id="primary", used_percent=55.0)],
    )

    store.record_snapshots([snap1, snap2])

    history = store.get_history(account_id="codex-primary", hours=1)
    assert len(history) == 2
    assert history[0].used_percent == 45.0
    assert history[1].used_percent == 55.0


def test_history_store_prune() -> None:
    store = HistoryStore(":memory:")
    old_time = datetime.now(UTC) - timedelta(days=40)

    snap_old = UsageSnapshot(
        account_id="codex-primary",
        provider="codex",
        configured_email="test@example.com",
        status=AccountStatus.LIVE,
        source="test",
        retrieved_at=old_time,
        windows=[UsageWindow(id="primary", used_percent=30.0)],
    )
    store.record_snapshots([snap_old])

    deleted = store.prune(max_days=30)
    assert deleted == 1
    assert len(store.get_history(hours=1000)) == 0


def test_history_store_deduplication_and_heatmap() -> None:
    store = HistoryStore(":memory:")
    now = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)

    snap = UsageSnapshot(
        account_id="codex-primary",
        provider="codex",
        configured_email="test@example.com",
        status=AccountStatus.LIVE,
        source="test",
        retrieved_at=now,
        windows=[UsageWindow(id="primary", used_percent=50.0)],
    )

    # First record should be inserted
    store.record_snapshots([snap])
    # Immediate duplicate should be skipped
    store.record_snapshots([snap])

    history = store.get_history(account_id="codex-primary", hours=24)
    assert len(history) == 1

    heatmap = store.get_hourly_heatmap(account_id="codex-primary", days=7)
    assert len(heatmap) == 24
    hour_14 = next(h for h in heatmap if h.hour == 14)
    assert hour_14.average_percent == 50.0
    assert hour_14.samples_count == 1
