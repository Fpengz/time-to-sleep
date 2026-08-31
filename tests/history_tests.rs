use chrono::{DateTime, Duration, Utc};
use rusqlite::{params, Connection};
use std::path::PathBuf;
use time_to_sleep::domain::{AccountStatus, ErrorCode, ProviderName, UsageSnapshot, UsageWindow};
use time_to_sleep::history::HistoryStore;

fn snapshot(
    observed_at: DateTime<Utc>,
    retrieved_at: DateTime<Utc>,
    used_percent: f64,
) -> UsageSnapshot {
    UsageSnapshot {
        account_id: "codex-primary".into(),
        provider: ProviderName::Codex,
        configured_email: "test@example.com".into(),
        observed_email: Some("test@example.com".into()),
        status: AccountStatus::Live,
        error_code: ErrorCode::None,
        message: None,
        source: "test".into(),
        plan_type: None,
        observed_at: Some(observed_at),
        retrieved_at: Some(retrieved_at),
        windows: vec![UsageWindow {
            id: "primary".into(),
            used_percent,
            window_minutes: Some(300),
            resets_at: None,
            raw_limits: None,
        }],
    }
}

fn temp_db_path(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "time-to-sleep-{label}-{}-{}.db",
        std::process::id(),
        Utc::now().timestamp_nanos_opt().unwrap_or_default()
    ))
}

#[test]
fn test_history_store_deduplication_and_ranges() {
    let store = HistoryStore::new(None).expect("failed to create in-memory store");
    let now = Utc::now();

    let snap1 = snapshot(
        now - Duration::minutes(10),
        now - Duration::minutes(10),
        25.0,
    );
    let snap2 = snapshot(now - Duration::minutes(8), now - Duration::minutes(8), 25.0);

    store.record_snapshots(&[snap1, snap2]).unwrap();

    let history = store.get_history(Some("codex-primary"), 24).unwrap();
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].used_percent, 25.0);

    let heatmap = store.get_hourly_heatmap(Some("codex-primary"), 7).unwrap();
    assert_eq!(heatmap.len(), 24);
}

#[test]
fn test_history_prefers_observed_at_over_retrieved_at() {
    let store = HistoryStore::new(None).unwrap();
    let retrieved_at = Utc::now();
    let observed_at = retrieved_at - Duration::hours(2);

    store
        .record_snapshots(&[snapshot(observed_at, retrieved_at, 31.0)])
        .unwrap();

    let history = store.get_history(Some("codex-primary"), 24).unwrap();
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].observed_at, observed_at);
}

#[test]
fn test_failed_transaction_does_not_poison_dedup_cache() {
    let path = temp_db_path("retry-after-failure");
    let store = HistoryStore::new(Some(&path)).unwrap();
    let conn = Connection::open(&path).unwrap();
    conn.execute_batch(
        "
        CREATE TRIGGER fail_history_insert
        BEFORE INSERT ON usage_history
        BEGIN
            SELECT RAISE(FAIL, 'forced failure');
        END;
        ",
    )
    .unwrap();

    let now = Utc::now();
    let snap = snapshot(now, now, 42.0);
    assert!(store.record_snapshots(&[snap.clone()]).is_err());

    conn.execute_batch("DROP TRIGGER fail_history_insert;")
        .unwrap();
    store.record_snapshots(&[snap]).unwrap();

    let history = store.get_history(Some("codex-primary"), 24).unwrap();
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].used_percent, 42.0);

    drop(conn);
    drop(store);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn test_history_rejects_malformed_persisted_timestamp() {
    let path = temp_db_path("malformed-timestamp");
    let store = HistoryStore::new(Some(&path)).unwrap();
    let conn = Connection::open(&path).unwrap();

    conn.execute(
        "INSERT INTO usage_history (account_id, provider, window_id, used_percent, observed_at) VALUES (?, ?, ?, ?, ?)",
        params!["codex-primary", "codex", "primary", 50.0, "not-a-timestamp"],
    )
    .unwrap();

    let error = store
        .get_history(Some("codex-primary"), 24)
        .expect_err("malformed timestamps should be surfaced");
    assert!(error
        .to_string()
        .contains("invalid observed_at value in usage_history"));

    drop(conn);
    drop(store);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn test_history_creates_account_window_time_index() {
    let path = temp_db_path("window-index");
    let store = HistoryStore::new(Some(&path)).unwrap();
    let conn = Connection::open(&path).unwrap();

    let count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_history_account_window_time'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 1);

    drop(conn);
    drop(store);
    let _ = std::fs::remove_file(&path);
}
