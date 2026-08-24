use chrono::Utc;
use time_to_sleep::cli::{format_prompt, format_table};
use time_to_sleep::domain::{AccountStatus, ErrorCode, ProviderName, UsageSnapshot, UsageWindow};

fn make_sample_snapshots() -> Vec<UsageSnapshot> {
    vec![
        UsageSnapshot {
            account_id: "codex-primary".into(),
            provider: ProviderName::Codex,
            configured_email: "test1@example.com".into(),
            observed_email: Some("test1@example.com".into()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "codex_live".into(),
            plan_type: Some("plus".into()),
            observed_at: Some(Utc::now()),
            retrieved_at: Some(Utc::now()),
            windows: vec![
                UsageWindow {
                    id: "primary".into(),
                    used_percent: 63.5,
                    window_minutes: Some(300),
                    resets_at: None,
                    raw_limits: None,
                },
                UsageWindow {
                    id: "secondary".into(),
                    used_percent: 15.0,
                    window_minutes: Some(10080),
                    resets_at: None,
                    raw_limits: None,
                },
            ],
        },
        UsageSnapshot {
            account_id: "claude".into(),
            provider: ProviderName::Claude,
            configured_email: "test2@example.com".into(),
            observed_email: Some("test2@example.com".into()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "claude_live".into(),
            plan_type: Some("pro".into()),
            observed_at: Some(Utc::now()),
            retrieved_at: Some(Utc::now()),
            windows: vec![UsageWindow {
                id: "primary".into(),
                used_percent: 82.0,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        },
    ]
}

#[test]
fn test_format_prompt_compact() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "compact");
    assert!(prompt.starts_with('['));
    assert!(prompt.ends_with(']'));
    assert!(prompt.contains("Codex:64%"));
    assert!(prompt.contains("Claude:82%"));
}

#[test]
fn test_format_prompt_json() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "json");
    let val: serde_json::Value = serde_json::from_str(&prompt).unwrap();
    assert_eq!(val["accounts"].as_array().unwrap().len(), 2);
    assert_eq!(val["needs_attention"].as_bool().unwrap(), false);
}

#[test]
fn test_format_prompt_starship() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "starship");
    assert!(prompt.contains("Codex:64%"));
    assert!(prompt.contains("Claude:82%"));
}

#[test]
fn test_format_prompt_tmux() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "tmux");
    assert!(prompt.contains("Codex:64%"));
    assert!(prompt.contains("Claude:82%"));
}

#[test]
fn test_format_prompt_waybar() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "waybar");
    let val: serde_json::Value = serde_json::from_str(&prompt).unwrap();
    assert!(val.get("text").is_some());
    assert!(val.get("tooltip").is_some());
}

#[test]
fn test_format_prompt_sketchybar() {
    let snapshots = make_sample_snapshots();
    let prompt = format_prompt(&snapshots, "sketchybar");
    assert!(prompt.contains("Codex:64%"));
    assert!(prompt.contains("Claude:82%"));
}

#[test]
fn test_format_table() {
    let snapshots = make_sample_snapshots();
    let table = format_table(&snapshots);
    assert!(table.contains("Provider"));
    assert!(table.contains("Account"));
    assert!(table.contains("Codex"));
    assert!(table.contains("Claude"));
    assert!(table.contains("63.5%"));
    assert!(table.contains("82.0%"));
}
