use chrono::Utc;
use std::collections::HashMap;
use time_to_sleep::domain::{
    AccountConfig, AccountStatus, ErrorCode, ProviderName, Settings, UsageSnapshot, UsageWindow,
};
use time_to_sleep::services::{AnalyticsService, UsageService};

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
                auto_retrieval: true,
            },
            AccountConfig {
                id: "claude".into(),
                provider: ProviderName::Claude,
                email: "test@example.com".into(),
                home: "/tmp".into(),
                priority: 0,
                warning_threshold: 80.0,
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

#[tokio::test]
async fn test_usage_service_empty_providers() {
    let service = UsageService::new(HashMap::new());
    let settings = Settings::default();
    let snapshots = service.collect(&settings, false).await;
    assert!(snapshots.is_empty());
}
