use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::domain::UsageWindow;

#[derive(Debug, Clone)]
pub struct ParsedWindows {
    pub observed_at: DateTime<Utc>,
    pub windows: Vec<UsageWindow>,
}

pub fn parse_timestamp(val: &Value, milliseconds: bool) -> Result<DateTime<Utc>> {
    if let Some(n) = val.as_i64() {
        let secs = if milliseconds { n / 1000 } else { n };
        let nsecs = if milliseconds { ((n % 1000) * 1_000_000) as u32 } else { 0 };
        return DateTime::from_timestamp(secs, nsecs)
            .context("invalid unix timestamp");
    }
    if let Some(f) = val.as_f64() {
        let secs = if milliseconds { (f / 1000.0) as i64 } else { f as i64 };
        let nsecs = if milliseconds { ((f % 1000.0) * 1_000_000.0) as u32 } else { 0 };
        return DateTime::from_timestamp(secs, nsecs)
            .context("invalid unix float timestamp");
    }
    if let Some(s) = val.as_str() {
        if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
            return Ok(dt.with_timezone(&Utc));
        }
        let fixed = s.replace('Z', "+00:00");
        if let Ok(dt) = DateTime::parse_from_rfc3339(&fixed) {
            return Ok(dt.with_timezone(&Utc));
        }
    }
    bail!("unsupported timestamp format: {:?}", val)
}

pub fn parse_codex_rollout(lines: &[&str]) -> Result<ParsedWindows> {
    let mut newest: Option<(DateTime<Utc>, Vec<UsageWindow>)> = None;

    for line in lines {
        let Ok(event): Result<Value, _> = serde_json::from_str(line) else {
            continue;
        };
        let Some(ts_val) = event.get("timestamp") else {
            continue;
        };
        let Ok(ts) = parse_timestamp(ts_val, false) else {
            continue;
        };

        let Some(raw_limits) = event.pointer("/payload/rate_limits").and_then(|v| v.as_object()) else {
            continue;
        };

        let mut windows = Vec::new();
        for (key, val) in raw_limits {
            if (key == "primary" || key == "secondary") && val.is_object() {
                let used = val.get("used_percent").or_else(|| val.get("usedPercent")).and_then(|v| v.as_f64()).unwrap_or(0.0);
                let duration = val.get("window_minutes").or_else(|| val.get("windowDurationMins")).and_then(|v| v.as_i64());
                let reset = val.get("resets_at").or_else(|| val.get("resetsAt")).and_then(|v| parse_timestamp(v, false).ok());

                windows.push(UsageWindow {
                    id: key.clone(),
                    used_percent: used,
                    window_minutes: duration,
                    resets_at: reset,
                    raw_limits: None,
                });
            }
        }

        if !windows.is_empty() && newest.as_ref().is_none_or(|(prev_ts, _)| ts > *prev_ts) {
            newest = Some((ts, windows));
        }
    }

    if let Some((ts, windows)) = newest {
        Ok(ParsedWindows {
            observed_at: ts,
            windows,
        })
    } else {
        bail!("no valid Codex rate limit event found")
    }
}

pub fn parse_antigravity_quota_summary(document: &Value) -> Result<ParsedWindows> {
    let response = document.get("response").unwrap_or(document);
    let groups = response.get("groups").and_then(|v| v.as_array()).context("no groups in quota summary")?;

    let mut windows = Vec::new();
    for group in groups {
        let group_name = group.get("displayName").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
        let group_id = if group_name.contains("gemini") { "gemini" } else { "third_party" };

        if let Some(buckets) = group.get("buckets").and_then(|v| v.as_array()) {
            for bucket in buckets {
                let remaining = match bucket.get("remainingFraction").and_then(|v| v.as_f64()) {
                    Some(r) if (0.0..=1.0).contains(&r) => r,
                    _ => continue,
                };
                let bucket_id = bucket.get("bucketId").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
                let window_kind = bucket.get("window").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();

                let (suffix, duration) = if bucket_id.contains("weekly") || window_kind == "weekly" {
                    ("weekly", Some(10080))
                } else if bucket_id.contains("5h") || window_kind == "5h" || window_kind == "five_hour" || window_kind == "five-hour" {
                    ("five_hour", Some(300))
                } else {
                    (bucket_id.as_str(), None)
                };

                let resets_at = bucket.get("resetTime").and_then(|v| parse_timestamp(v, false).ok());

                windows.push(UsageWindow {
                    id: format!("{}_{}", group_id, suffix.replace('-', "_")),
                    used_percent: ((1.0 - remaining) * 10000.0).round() / 100.0,
                    window_minutes: duration,
                    resets_at,
                    raw_limits: None,
                });
            }
        }
    }

    if windows.is_empty() {
        bail!("no valid quota buckets found");
    }

    Ok(ParsedWindows {
        observed_at: Utc::now(),
        windows,
    })
}
