use chrono::{Duration, Utc};
use time_to_sleep::domain::{AccountStatus, ErrorCode, ProviderName, UsageSnapshot, UsageWindow};
use time_to_sleep::history::HistoryStore;

#[test]
fn test_history_store_deduplication_and_ranges() {
    let store = HistoryStore::new(None).expect("failed to create in-memory store");
    let now = Utc::now();

    let snap1 = UsageSnapshot {
        account_id: "codex-primary".into(),
        provider: ProviderName::Codex,
        configured_email: "test@example.com".into(),
        observed_email: Some("test@example.com".into()),
        status: AccountStatus::Live,
        error_code: ErrorCode::None,
        message: None,
        source: "test".into(),
        plan_type: None,
        observed_at: Some(now - Duration::minutes(10)),
        retrieved_at: Some(now - Duration::minutes(10)),
        windows: vec![UsageWindow {
            id: "primary".into(),
            used_percent: 25.0,
            window_minutes: Some(300),
            resets_at: None,
            raw_limits: None,
        }],
    };

    let snap2 = UsageSnapshot {
        account_id: "codex-primary".into(),
        provider: ProviderName::Codex,
        configured_email: "test@example.com".into(),
        observed_email: Some("test@example.com".into()),
        status: AccountStatus::Live,
        error_code: ErrorCode::None,
        message: None,
        source: "test".into(),
        plan_type: None,
        observed_at: Some(now - Duration::minutes(8)), // within 5 min of snap1, same percentage
        retrieved_at: Some(now - Duration::minutes(8)),
        windows: vec![UsageWindow {
            id: "primary".into(),
            used_percent: 25.0,
            window_minutes: Some(300),
            resets_at: None,
            raw_limits: None,
        }],
    };

    store.record_snapshots(&[snap1, snap2]).unwrap();

    let history = store.get_history(Some("codex-primary"), 24).unwrap();
    assert_eq!(history.len(), 1); // second snapshot deduplicated
    assert_eq!(history[0].used_percent, 25.0);

    let heatmap = store.get_hourly_heatmap(Some("codex-primary"), 7).unwrap();
    assert_eq!(heatmap.len(), 24);
}
