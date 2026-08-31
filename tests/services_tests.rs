use chrono::{DateTime, Duration, Utc};
use std::collections::HashMap;
use time_to_sleep::domain::{
    AccountConfig, AccountStatus, ErrorCode, HistoryPoint, ProviderName, Settings, UsageSnapshot,
    UsageWindow,
};
use time_to_sleep::services::{AnalyticsService, UsageService};

fn test_window(id: &str, used_percent: f64) -> UsageWindow {
    UsageWindow {
        id: id.to_string(),
        used_percent,
        window_minutes: None,
        resets_at: None,
        raw_limits: None,
    }
}

fn test_snapshot(at: DateTime<Utc>, windows: Vec<UsageWindow>) -> UsageSnapshot {
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
        observed_at: Some(at),
        retrieved_at: Some(at),
        windows,
    }
}

#[test]
fn test_analytics_service_smart_routing() {
    let analytics = AnalyticsService::new();
    let now = Utc::now();

    let snapshots = vec![
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
            observed_at: Some(now),
            retrieved_at: Some(now),
            windows: vec![UsageWindow {
                id: "primary".into(),
                used_percent: 85.0,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        },
        UsageSnapshot {
            account_id: "claude".into(),
            provider: ProviderName::Claude,
            configured_email: "test@example.com".into(),
            observed_email: Some("test@example.com".into()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "test".into(),
            plan_type: None,
            observed_at: Some(now),
            retrieved_at: Some(now),
            windows: vec![UsageWindow {
                id: "primary".into(),
                used_percent: 20.0,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        },
    ];

    let settings = Settings {
        accounts: vec![
            AccountConfig {
                id: "codex-primary".into(),
                provider: ProviderName::Codex,
                email: "test@example.com".into(),
                home: "/tmp".into(),
                priority: 0,
                warning_threshold: 80.0,
                critical_threshold: 95.0,
                auto_retrieval: true,
            },
            AccountConfig {
                id: "claude".into(),
                provider: ProviderName::Claude,
                email: "test@example.com".into(),
                home: "/tmp".into(),
                priority: 0,
                warning_threshold: 80.0,
                critical_threshold: 95.0,
                auto_retrieval: true,
            },
        ],
        ..Default::default()
    };

    let result = analytics.analyze(&snapshots, Some(&settings));
    assert_eq!(result.accounts.len(), 2);

    let claude_acc = result
        .accounts
        .iter()
        .find(|a| a.account_id == "claude")
        .unwrap();
    assert!(claude_acc.recommended);

    let codex_acc = result
        .accounts
        .iter()
        .find(|a| a.account_id == "codex-primary")
        .unwrap();
    assert!(!codex_acc.recommended);
}

#[test]
fn test_analytics_uses_history_for_current_limiting_window() {
    let analytics = AnalyticsService::new();
    let now = Utc::now();
    let one_hour_ago = now - Duration::hours(1);

    let first = test_snapshot(
        one_hour_ago,
        vec![
            test_window("five_hour", 40.0),
            test_window("seven_day", 70.0),
        ],
    );
    analytics.analyze(&[first], None);

    let second = test_snapshot(
        now,
        vec![
            test_window("five_hour", 75.0),
            test_window("seven_day", 71.0),
        ],
    );
    let result = analytics.analyze(&[second], None);
    let account = &result.accounts[0];

    assert_eq!(account.current_percent, 75.0);
    assert_eq!(account.limiting_window_id.as_deref(), Some("five_hour"));
    assert_eq!(account.burn_rate_per_hour, Some(35.0));
    assert_eq!(account.minutes_to_exhaustion, Some(43));
}

#[test]
fn test_analytics_ignores_samples_before_latest_reset() {
    let analytics = AnalyticsService::new();
    let now = Utc::now();

    analytics.analyze(
        &[test_snapshot(
            now - Duration::hours(2),
            vec![test_window("five_hour", 90.0)],
        )],
        None,
    );
    analytics.analyze(
        &[test_snapshot(
            now - Duration::hours(1),
            vec![test_window("five_hour", 5.0)],
        )],
        None,
    );

    let result = analytics.analyze(
        &[test_snapshot(now, vec![test_window("five_hour", 10.0)])],
        None,
    );
    let account = &result.accounts[0];

    assert_eq!(account.limiting_window_id.as_deref(), Some("five_hour"));
    assert_eq!(account.burn_rate_per_hour, Some(5.0));
    assert_eq!(account.minutes_to_exhaustion, Some(1080));
}

#[test]
fn test_analytics_can_resume_from_persisted_history() {
    let now = Utc::now();
    let seed = vec![HistoryPoint {
        account_id: "codex-primary".into(),
        provider: "codex".into(),
        window_id: "five_hour".into(),
        used_percent: 20.0,
        observed_at: now - Duration::hours(1),
    }];
    let analytics = AnalyticsService::from_history(&seed);

    let result = analytics.analyze(
        &[test_snapshot(now, vec![test_window("five_hour", 30.0)])],
        None,
    );
    let account = &result.accounts[0];

    assert_eq!(account.limiting_window_id.as_deref(), Some("five_hour"));
    assert_eq!(account.burn_rate_per_hour, Some(10.0));
    assert_eq!(account.minutes_to_exhaustion, Some(420));
}

#[tokio::test]
async fn test_usage_service_empty_providers() {
    let service = UsageService::new(HashMap::new());
    let settings = Settings::default();
    let snapshots = service.collect(&settings, false).await;
    assert!(snapshots.is_empty());
}
