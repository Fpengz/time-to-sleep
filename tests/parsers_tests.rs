use serde_json::json;
use time_to_sleep::providers::parsers::{
    parse_antigravity_quota_summary, parse_codex_rollout, parse_timestamp,
};

#[test]
fn test_parse_timestamp_formats() {
    // Unix int seconds
    let ts_int = json!(1724500000);
    let dt = parse_timestamp(&ts_int, false).unwrap();
    assert_eq!(dt.timestamp(), 1724500000);

    // Unix milliseconds
    let ts_ms = json!(1724500000000i64);
    let dt_ms = parse_timestamp(&ts_ms, true).unwrap();
    assert_eq!(dt_ms.timestamp(), 1724500000);

    // RFC3339 string
    let ts_str = json!("2026-08-24T12:00:00Z");
    let dt_str = parse_timestamp(&ts_str, false).unwrap();
    assert_eq!(dt_str.timestamp(), 1787572800);
}

#[test]
fn test_parse_codex_rollout() {
    let line1 = r#"{"timestamp": 1724500000, "payload": {"rate_limits": {"primary": {"used_percent": 45.0, "window_minutes": 300}, "secondary": {"used_percent": 10.0, "window_minutes": 10080}}}}"#;
    let line2 = r#"{"timestamp": 1724500100, "payload": {"rate_limits": {"primary": {"used_percent": 50.0, "window_minutes": 300}, "secondary": {"used_percent": 12.0, "window_minutes": 10080}}}}"#;

    let res = parse_codex_rollout(&[line1, line2]).unwrap();
    assert_eq!(res.observed_at.timestamp(), 1724500100);
    assert_eq!(res.windows.len(), 2);

    let primary = res.windows.iter().find(|w| w.id == "primary").unwrap();
    assert_eq!(primary.used_percent, 50.0);
    assert_eq!(primary.window_minutes, Some(300));
}

#[test]
fn test_parse_antigravity_quota_summary() {
    let doc = json!({
        "response": {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "bucketId": "five_hour",
                            "remainingFraction": 0.75,
                            "window": "5h"
                        },
                        {
                            "bucketId": "weekly",
                            "remainingFraction": 0.90,
                            "window": "weekly"
                        }
                    ]
                }
            ]
        }
    });

    let res = parse_antigravity_quota_summary(&doc).unwrap();
    assert_eq!(res.windows.len(), 2);
    let five_hour = res
        .windows
        .iter()
        .find(|w| w.id.contains("five_hour"))
        .unwrap();
    assert_eq!(five_hour.used_percent, 25.0);
    let weekly = res
        .windows
        .iter()
        .find(|w| w.id.contains("weekly"))
        .unwrap();
    assert_eq!(weekly.used_percent, 10.0);
}
