use std::collections::HashMap;
use std::sync::Mutex;

use chrono::{DateTime, Utc};

use crate::domain::{
    AccountAnalytics, AccountStatus, AnalyticsResponse, HistoryPoint, Settings, UsageSnapshot,
};

type WindowHistoryKey = (String, String);
type WindowHistoryMap = HashMap<WindowHistoryKey, Vec<(DateTime<Utc>, f64)>>;

const MAX_HISTORY_POINTS: usize = 60;
const REPLACE_WITHIN_SECS: i64 = 10;
const RESET_DROP_THRESHOLD: f64 = 5.0;
const MIN_BURN_RATE_PER_HOUR: f64 = 0.1;

pub struct AnalyticsService {
    history: Mutex<WindowHistoryMap>,
}

impl Default for AnalyticsService {
    fn default() -> Self {
        Self::new()
    }
}

impl AnalyticsService {
    pub fn new() -> Self {
        Self {
            history: Mutex::new(HashMap::new()),
        }
    }

    pub fn from_history(points: &[HistoryPoint]) -> Self {
        let mut histories: WindowHistoryMap = HashMap::new();
        for point in points {
            histories
                .entry((point.account_id.clone(), point.window_id.clone()))
                .or_default()
                .push((point.observed_at, point.used_percent));
        }

        for history in histories.values_mut() {
            history.sort_by_key(|a| a.0);
            Self::trim_history(history);
        }

        Self {
            history: Mutex::new(histories),
        }
    }

    fn trim_history(history: &mut Vec<(DateTime<Utc>, f64)>) {
        if history.len() > MAX_HISTORY_POINTS {
            let remove = history.len() - MAX_HISTORY_POINTS;
            history.drain(0..remove);
        }
    }

    pub fn record_snapshot(&self, snapshot: &UsageSnapshot) {
        if snapshot.windows.is_empty() {
            return;
        }

        // Prefer the time at which the provider data was actually observed. A cached
        // retrieval should not look like a fresh quota sample merely because it was read now.
        let ts = snapshot
            .observed_at
            .or(snapshot.retrieved_at)
            .unwrap_or_else(Utc::now);

        let mut hist_map = self.history.lock().unwrap();
        for window in &snapshot.windows {
            let hist = hist_map
                .entry((snapshot.account_id.clone(), window.id.clone()))
                .or_default();

            if let Some(last) = hist.last_mut() {
                let delta_secs = (ts - last.0).num_seconds();
                if delta_secs.abs() < REPLACE_WITHIN_SECS {
                    *last = (ts, window.used_percent);
                    continue;
                }
                if delta_secs < 0 {
                    // Ignore stale cached observations that predate the newest known point.
                    continue;
                }
            }

            hist.push((ts, window.used_percent));
            Self::trim_history(hist);
        }
    }

    fn velocity(history: &[(DateTime<Utc>, f64)], current_pct: f64) -> (Option<f64>, Option<i64>) {
        if history.len() < 2 {
            return (None, None);
        }

        // A meaningful downward jump indicates that the quota window reset. Only derive
        // velocity from samples after the most recent reset instead of averaging across it.
        let segment_start = history
            .windows(2)
            .rposition(|pair| pair[1].1 + RESET_DROP_THRESHOLD < pair[0].1)
            .map(|index| index + 1)
            .unwrap_or(0);
        let segment = &history[segment_start..];
        if segment.len() < 2 {
            return (None, None);
        }

        let (first_ts, first_pct) = segment[0];
        let (last_ts, last_pct) = *segment.last().unwrap();
        let delta_sec = (last_ts - first_ts).num_seconds() as f64;
        if delta_sec < 60.0 {
            return (None, None);
        }

        let rate = (last_pct - first_pct) / (delta_sec / 3600.0);
        if rate <= MIN_BURN_RATE_PER_HOUR {
            return (None, None);
        }

        let rounded_rate = (rate * 100.0).round() / 100.0;
        let remaining = (100.0 - current_pct).max(0.0);
        let minutes_to_exhaustion = if remaining > 0.0 {
            Some((((remaining / rounded_rate) * 60.0).round() as i64).max(1))
        } else {
            None
        };

        (Some(rounded_rate), minutes_to_exhaustion)
    }

    pub fn analyze(
        &self,
        snapshots: &[UsageSnapshot],
        settings: Option<&Settings>,
    ) -> AnalyticsResponse {
        for s in snapshots {
            self.record_snapshot(s);
        }

        let now = Utc::now();
        let mut thresholds_map = HashMap::new();
        if let Some(cfg) = settings {
            for acc in &cfg.accounts {
                thresholds_map.insert(acc.id.as_str(), acc.warning_threshold);
            }
        }

        let hist_map = self.history.lock().unwrap();

        struct EvalItem<'a> {
            snapshot: &'a UsageSnapshot,
            current_pct: f64,
            limiting_window_id: Option<String>,
            burn_rate: Option<f64>,
            minutes_to_exhaust: Option<i64>,
        }

        let mut evaluated = Vec::with_capacity(snapshots.len());
        for s in snapshots {
            let limiting_window = s.windows.iter().max_by(|a, b| {
                a.used_percent
                    .partial_cmp(&b.used_percent)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            let (current_pct, limiting_window_id, burn_rate, minutes_to_exhaust) =
                if let Some(window) = limiting_window {
                    let key = (s.account_id.clone(), window.id.clone());
                    let (burn_rate, minutes_to_exhaust) = hist_map
                        .get(&key)
                        .map(|history| Self::velocity(history, window.used_percent))
                        .unwrap_or((None, None));
                    (
                        window.used_percent,
                        Some(window.id.clone()),
                        burn_rate,
                        minutes_to_exhaust,
                    )
                } else {
                    (0.0, None, None, None)
                };

            evaluated.push(EvalItem {
                snapshot: s,
                current_pct,
                limiting_window_id,
                burn_rate,
                minutes_to_exhaust,
            });
        }

        let mut healthy_alternatives = Vec::new();
        let mut high_usage_accounts = Vec::new();

        for item in &evaluated {
            if item.snapshot.status == AccountStatus::Live {
                if item.current_pct < 50.0 {
                    healthy_alternatives.push((
                        item.snapshot.account_id.as_str(),
                        item.snapshot.provider,
                        item.current_pct,
                    ));
                }
                let threshold = thresholds_map
                    .get(item.snapshot.account_id.as_str())
                    .copied()
                    .unwrap_or(80.0);
                if item.current_pct >= threshold {
                    high_usage_accounts.push((
                        item.snapshot.account_id.as_str(),
                        item.snapshot.provider,
                        item.current_pct,
                    ));
                }
            }
        }

        let mut suggestions = Vec::new();
        for (acc_id, prov, curr_pct) in &high_usage_accounts {
            let prov_name = prov.display_name();
            if !healthy_alternatives.is_empty() {
                let alt_names = healthy_alternatives
                    .iter()
                    .map(|(a_id, p, _)| format!("{} ({})", p.display_name(), a_id))
                    .collect::<Vec<_>>()
                    .join(", ");
                suggestions.push(format!(
                    "{} ({}) is at {:.1}%. Recommended alternatives: {}.",
                    prov_name, acc_id, curr_pct, alt_names
                ));
            } else {
                suggestions.push(format!(
                    "{} ({}) is near limit ({:.1}%).",
                    prov_name, acc_id, curr_pct
                ));
            }
        }

        for item in &evaluated {
            if item.snapshot.status == AccountStatus::RateLimited {
                suggestions.push(format!(
                    "{} ({}) is currently rate-limited.",
                    item.snapshot.provider.display_name(),
                    item.snapshot.account_id
                ));
            }
        }

        let recommended_id = healthy_alternatives
            .iter()
            .min_by(|a, b| a.2.partial_cmp(&b.2).unwrap_or(std::cmp::Ordering::Equal))
            .map(|a| a.0);

        let final_accounts = evaluated
            .into_iter()
            .map(|item| {
                let is_rec = recommended_id == Some(item.snapshot.account_id.as_str());
                let reason = if is_rec {
                    Some("Lowest active usage".to_string())
                } else {
                    None
                };
                AccountAnalytics {
                    account_id: item.snapshot.account_id.clone(),
                    provider: item.snapshot.provider,
                    current_percent: item.current_pct,
                    limiting_window_id: item.limiting_window_id,
                    burn_rate_per_hour: item.burn_rate,
                    minutes_to_exhaustion: item.minutes_to_exhaust,
                    status: item.snapshot.status,
                    recommended: is_rec,
                    recommendation_reason: reason,
                }
            })
            .collect();

        AnalyticsResponse {
            generated_at: now,
            accounts: final_accounts,
            suggestions,
        }
    }
}
