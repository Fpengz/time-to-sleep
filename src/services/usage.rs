use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use tokio::sync::RwLock;
use tokio::time::timeout;

use crate::domain::{AccountStatus, ErrorCode, ProviderName, Settings, UsageSnapshot};
use crate::providers::UsageProvider;

type CachedSnapshotMap = HashMap<String, (UsageSnapshot, DateTime<Utc>)>;

pub struct UsageService {
    providers: HashMap<ProviderName, Arc<dyn UsageProvider>>,
    ttls: HashMap<ProviderName, chrono::Duration>,
    timeouts: HashMap<ProviderName, Duration>,
    cache: Arc<RwLock<CachedSnapshotMap>>,
}

impl UsageService {
    pub fn new(providers: HashMap<ProviderName, Arc<dyn UsageProvider>>) -> Self {
        // Codex/Antigravity fetches spawn a subprocess (codex app-server, ps/lsof scans),
        // so TTLs stay well above the dashboard's poll interval to avoid re-spawning
        // those processes on every tick.
        let mut ttls = HashMap::new();
        ttls.insert(ProviderName::Codex, chrono::Duration::seconds(180));
        ttls.insert(ProviderName::Claude, chrono::Duration::seconds(300));
        ttls.insert(ProviderName::Antigravity, chrono::Duration::seconds(90));

        let mut timeouts = HashMap::new();
        timeouts.insert(ProviderName::Codex, Duration::from_secs(15));
        timeouts.insert(ProviderName::Claude, Duration::from_secs(10));
        timeouts.insert(ProviderName::Antigravity, Duration::from_secs(8));

        Self {
            providers,
            ttls,
            timeouts,
            cache: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub async fn get_cached(&self, account_id: &str) -> Option<UsageSnapshot> {
        self.cache
            .read()
            .await
            .get(account_id)
            .map(|(snap, _)| snap.clone())
    }

    pub async fn collect(&self, settings: &Settings, force_refresh: bool) -> Vec<UsageSnapshot> {
        let mut tasks = Vec::new();
        let now = Utc::now();

        for acc in &settings.accounts {
            let acc = acc.clone();
            let cache_lock = self.cache.clone();
            let provider = self.providers.get(&acc.provider).cloned();
            let ttl = self
                .ttls
                .get(&acc.provider)
                .copied()
                .unwrap_or(chrono::Duration::seconds(30));
            let timeout_dur = self
                .timeouts
                .get(&acc.provider)
                .copied()
                .unwrap_or(Duration::from_secs(10));

            tasks.push(tokio::spawn(async move {
                if !force_refresh {
                    let cache = cache_lock.read().await;
                    if let Some((snap, cached_time)) = cache.get(&acc.id) {
                        if now - *cached_time < ttl {
                            return snap.clone();
                        }
                    }
                }

                let snap = if let Some(p) = provider {
                    match timeout(timeout_dur, p.fetch(&acc)).await {
                        Ok(s) => s,
                        Err(_) => UsageSnapshot {
                            account_id: acc.id.clone(),
                            provider: acc.provider,
                            configured_email: acc.email.clone(),
                            observed_email: None,
                            status: AccountStatus::Unavailable,
                            error_code: ErrorCode::Timeout,
                            message: Some(format!(
                                "Provider {} timed out after {}s",
                                acc.provider,
                                timeout_dur.as_secs()
                            )),
                            source: acc.provider.as_str().to_string(),
                            plan_type: None,
                            observed_at: Some(now),
                            retrieved_at: Some(now),
                            windows: vec![],
                        },
                    }
                } else {
                    UsageSnapshot {
                        account_id: acc.id.clone(),
                        provider: acc.provider,
                        configured_email: acc.email.clone(),
                        observed_email: None,
                        status: AccountStatus::Unavailable,
                        error_code: ErrorCode::UpstreamError,
                        message: Some(format!("No provider registered for {}", acc.provider)),
                        source: acc.provider.as_str().to_string(),
                        plan_type: None,
                        observed_at: Some(now),
                        retrieved_at: Some(now),
                        windows: vec![],
                    }
                };

                let mut cache = cache_lock.write().await;
                cache.insert(acc.id.clone(), (snap.clone(), Utc::now()));
                snap
            }));
        }

        let mut results = Vec::new();
        for task in tasks {
            if let Ok(snap) = task.await {
                results.push(snap);
            }
        }

        results
    }
}
