use std::collections::HashMap;
use std::sync::Mutex;

use chrono::{DateTime, Utc};

use crate::domain::{
    AccountAnalytics, AccountStatus, AnalyticsResponse, Settings, UsageSnapshot,
};

type AccountHistoryMap = HashMap<String, Vec<(DateTime<Utc>, f64)>>;

pub struct AnalyticsService {
    history: Mutex<AccountHistoryMap>,
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

    pub fn record_snapshot(&self, snapshot: &UsageSnapshot) {
        if snapshot.windows.is_empty() {
            return;
        }
        let max_pct = snapshot
            .windows
            .iter()
            .map(|w| w.used_percent)
            .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .unwrap_or(0.0);

        let ts = snapshot.retrieved_at.unwrap_or_else(Utc::now);

        let mut hist_map = self.history.lock().unwrap();
        let hist = hist_map.entry(snapshot.account_id.clone()).or_default();

        if let Some(last) = hist.last_mut() {
            if (ts - last.0).num_seconds().abs() < 10 {
                *last = (ts, max_pct);
                return;
            }
        }
        hist.push((ts, max_pct));
        if hist.len() > 60 {
            hist.remove(0);
        }
    }

    pub fn analyze(&self, snapshots: &[UsageSnapshot], settings: Option<&Settings>) -> AnalyticsResponse {
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

        // 1. Evaluate metrics
        struct EvalItem<'a> {
            snapshot: &'a UsageSnapshot,
            current_pct: f64,
            burn_rate: Option<f64>,
            minutes_to_exhaust: Option<i64>,
        }

        let mut evaluated = Vec::with_capacity(snapshots.len());
        for s in snapshots {
            let current_pct = s
                .windows
                .iter()
                .map(|w| w.used_percent)
                .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
                .unwrap_or(0.0);

            let hist = hist_map.get(&s.account_id);
            let mut burn_rate = None;
            let mut minutes_to_exhaust = None;

            if let Some(h) = hist {
                if h.len() >= 2 {
                    let (first_ts, first_pct) = h[0];
                    let (last_ts, last_pct) = *h.last().unwrap();
                    let delta_sec = (last_ts - first_ts).num_seconds() as f64;
                    if delta_sec >= 60.0 {
                        let delta_hours = delta_sec / 3600.0;
                        let delta_pct = last_pct - first_pct;
                        let rate = delta_pct / delta_hours;
                        if rate > 0.1 {
                            let rounded_rate = (rate * 100.0).round() / 100.0;
                            burn_rate = Some(rounded_rate);
                            let remaining = 100.0 - current_pct;
                            if remaining > 0.0 {
                                minutes_to_exhaust = Some((((remaining / rounded_rate) * 60.0).round() as i64).max(1));
                            }
                        }
                    }
                }
            }

            evaluated.push(EvalItem {
                snapshot: s,
                current_pct,
                burn_rate,
                minutes_to_exhaust,
            });
        }

        // 2. Classify healthy alternatives and high usage
        let mut healthy_alternatives = Vec::new();
        let mut high_usage_accounts = Vec::new();

        for item in &evaluated {
            if item.snapshot.status == AccountStatus::Live {
                if item.current_pct < 50.0 {
                    healthy_alternatives.push((item.snapshot.account_id.as_str(), item.snapshot.provider, item.current_pct));
                }
                let threshold = thresholds_map.get(item.snapshot.account_id.as_str()).copied().unwrap_or(80.0);
                if item.current_pct >= threshold {
                    high_usage_accounts.push((item.snapshot.account_id.as_str(), item.snapshot.provider, item.current_pct));
                }
            }
        }

        // 3. Generate suggestions
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
                suggestions.push(format!("{} ({}) is near limit ({:.1}%).", prov_name, acc_id, curr_pct));
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

        // 4. Determine recommendation
        let recommended_id = healthy_alternatives
            .iter()
            .min_by(|a, b| a.2.partial_cmp(&b.2).unwrap_or(std::cmp::Ordering::Equal))
            .map(|a| a.0);

        let final_accounts = evaluated
            .into_iter()
            .map(|item| {
                let is_rec = recommended_id == Some(item.snapshot.account_id.as_str());
                let reason = if is_rec { Some("Lowest active usage".to_string()) } else { None };
                AccountAnalytics {
                    account_id: item.snapshot.account_id.clone(),
                    provider: item.snapshot.provider,
                    current_percent: item.current_pct,
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
