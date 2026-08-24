use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use chrono::{Duration, Utc};
use time_to_sleep::cli::formatters::format_prompt;
use time_to_sleep::domain::{
    AccountConfig, AccountStatus, ErrorCode, ProviderName, Settings, UsageSnapshot, UsageWindow,
};
use time_to_sleep::history::HistoryStore;
use time_to_sleep::providers::UsageProvider;
use time_to_sleep::services::{AnalyticsService, UsageService};

struct FakeProvider {
    snapshot: UsageSnapshot,
}

#[async_trait]
impl UsageProvider for FakeProvider {
    async fn fetch(&self, _account: &AccountConfig) -> UsageSnapshot {
        self.snapshot.clone()
    }
}

fn create_dummy_snapshots(count: usize) -> Vec<UsageSnapshot> {
    let now = Utc::now();
    let configs: Vec<(&str, ProviderName, &str, f64)> = vec![
        (
            "codex-primary",
            ProviderName::Codex,
            "wzf5350@gmail.com",
            63.5,
        ),
        (
            "codex-secondary",
            ProviderName::Codex,
            "wzf0513@gmail.com",
            12.0,
        ),
        ("claude", ProviderName::Claude, "wzf5350@gmail.com", 82.0),
        (
            "antigravity",
            ProviderName::Antigravity,
            "wzf5350@gmail.com",
            5.0,
        ),
    ];

    configs
        .into_iter()
        .take(count)
        .map(|(acc_id, prov, email, pct)| UsageSnapshot {
            account_id: acc_id.to_string(),
            provider: prov,
            configured_email: email.to_string(),
            observed_email: Some(email.to_string()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: format!("{}_live", prov.as_str()),
            plan_type: Some("pro".to_string()),
            observed_at: Some(now),
            retrieved_at: Some(now),
            windows: vec![
                UsageWindow {
                    id: "primary".to_string(),
                    used_percent: pct,
                    window_minutes: Some(300),
                    resets_at: None,
                    raw_limits: None,
                },
                UsageWindow {
                    id: "weekly".to_string(),
                    used_percent: (pct - 10.0).max(0.0),
                    window_minutes: Some(10080),
                    resets_at: None,
                    raw_limits: None,
                },
            ],
        })
        .collect()
}

#[tokio::main]
async fn main() {
    println!("══════════════════════════════════════════════════════════════════════");
    println!("        TIME-TO-SLEEP NATIVE RUST PROFILING & BENCHMARK REPORT        ");
    println!("══════════════════════════════════════════════════════════════════════");

    // [1] SQLite Storage Engine
    let store = HistoryStore::new(None).unwrap();
    let now = Utc::now();
    let mut raw_snapshots = Vec::new();
    for i in 0..1000 {
        let t = now - Duration::minutes((i as i64) * 10);
        raw_snapshots.push(UsageSnapshot {
            account_id: "codex-primary".to_string(),
            provider: ProviderName::Codex,
            configured_email: "test@example.com".to_string(),
            observed_email: None,
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "test".to_string(),
            plan_type: None,
            observed_at: Some(t),
            retrieved_at: Some(t),
            windows: vec![UsageWindow {
                id: "primary".to_string(),
                used_percent: ((i as f64) * 2.3) % 100.0,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        });
    }

    let t0_ingest = Instant::now();
    store.record_snapshots(&raw_snapshots).unwrap();
    let elapsed_ingest = t0_ingest.elapsed();

    let t0_heat = Instant::now();
    for _ in 0..100 {
        let _ = store.get_hourly_heatmap(Some("codex-primary"), 7).unwrap();
    }
    let elapsed_heat = t0_heat.elapsed();

    let t0_hist = Instant::now();
    for _ in 0..100 {
        let _ = store.get_history(Some("codex-primary"), 24).unwrap();
    }
    let elapsed_hist = t0_hist.elapsed();

    println!("\n[1] SQLite Storage Engine & History");
    println!(
        "  • Ingest 1k Records                      : {:.2} ms",
        elapsed_ingest.as_secs_f64() * 1000.0
    );
    println!(
        "  • Heatmap SQL Aggregation (100x)         : {:.2} ms ({:.3} ms/query)",
        elapsed_heat.as_secs_f64() * 1000.0,
        (elapsed_heat.as_secs_f64() * 1000.0) / 100.0
    );
    println!(
        "  • 24h History Query (100x)               : {:.2} ms ({:.3} ms/query)",
        elapsed_hist.as_secs_f64() * 1000.0,
        (elapsed_hist.as_secs_f64() * 1000.0) / 100.0
    );

    // [2] Analytics Service
    let analytics = AnalyticsService::new();
    let snapshots = create_dummy_snapshots(4);
    let settings = Settings {
        accounts: snapshots
            .iter()
            .map(|s| AccountConfig {
                id: s.account_id.clone(),
                provider: s.provider,
                email: s.configured_email.clone(),
                home: "/tmp".to_string(),
                priority: 0,
                warning_threshold: 80.0,
            })
            .collect(),
    };

    let t0_analytics = Instant::now();
    for _ in 0..1000 {
        let _ = analytics.analyze(&snapshots, Some(&settings));
    }
    let elapsed_analytics = t0_analytics.elapsed();

    println!("\n[2] Analytics & Routing Engine");
    println!(
        "  • Analytics & Routing (1k iterations)    : {:.2} ms ({:.3} ms/eval)",
        elapsed_analytics.as_secs_f64() * 1000.0,
        (elapsed_analytics.as_secs_f64() * 1000.0) / 1000.0
    );

    // [3] CLI Prompt & Formatters
    let t0_prompt = Instant::now();
    for _ in 0..10000 {
        let _ = format_prompt(&snapshots, "compact");
    }
    let elapsed_prompt = t0_prompt.elapsed();

    let t0_json = Instant::now();
    for _ in 0..10000 {
        let _ = format_prompt(&snapshots, "json");
    }
    let elapsed_json = t0_json.elapsed();

    println!("\n[3] Formatter & CLI Statusline");
    println!(
        "  • Compact Prompt Format (10k iterations) : {:.2} ms ({:.2} µs/call)",
        elapsed_prompt.as_secs_f64() * 1000.0,
        (elapsed_prompt.as_secs_f64() * 1_000_000.0) / 10000.0
    );
    println!(
        "  • JSON Prompt Format (10k iterations)    : {:.2} ms ({:.2} µs/call)",
        elapsed_json.as_secs_f64() * 1000.0,
        (elapsed_json.as_secs_f64() * 1_000_000.0) / 10000.0
    );

    // [4] Usage Retrieval & Cache Layer
    let mut providers: HashMap<ProviderName, Arc<dyn UsageProvider>> = HashMap::new();
    for s in &snapshots {
        providers.insert(
            s.provider,
            Arc::new(FakeProvider {
                snapshot: s.clone(),
            }),
        );
    }
    let usage_service = UsageService::new(providers);
    let _ = usage_service.collect(&settings, true).await;

    let t0_cache = Instant::now();
    for _ in 0..1000 {
        let _ = usage_service.collect(&settings, false).await;
    }
    let elapsed_cache = t0_cache.elapsed();

    println!("\n[4] Usage Retrieval & Cache Layer");
    println!(
        "  • UsageService Warm Cache Hit (1k calls) : {:.2} ms ({:.3} ms/collect)",
        elapsed_cache.as_secs_f64() * 1000.0,
        (elapsed_cache.as_secs_f64() * 1000.0) / 1000.0
    );
    println!("══════════════════════════════════════════════════════════════════════\n");
}
