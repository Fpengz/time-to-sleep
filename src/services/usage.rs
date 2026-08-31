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
    timeouts: HashMap<ProviderName, Duration>,
    cache: Arc<RwLock<CachedSnapshotMap>>,
}

impl UsageService {
    pub fn new(providers: HashMap<ProviderName, Arc<dyn UsageProvider>>) -> Self {
        let mut timeouts = HashMap::new();
        timeouts.insert(ProviderName::Codex, Duration::from_secs(15));
        timeouts.insert(ProviderName::Claude, Duration::from_secs(10));
        timeouts.insert(ProviderName::Antigravity, Duration::from_secs(8));

        Self {
            providers,
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
            let task_account = acc.clone();
            let cache_lock = self.cache.clone();
            let provider = self.providers.get(&acc.provider).cloned();

            let ttl_secs = settings.auto_retrieval.ttl_for_provider(&acc.provider);
            let ttl = chrono::Duration::seconds(ttl_secs as i64);

            let timeout_dur = self
                .timeouts
                .get(&acc.provider)
                .copied()
                .unwrap_or(Duration::from_secs(10));
            let auto_retrieval_allowed = settings.auto_retrieval.enabled && acc.auto_retrieval;

            let handle = tokio::spawn(async move {
                if !force_refresh {
                    let cache = cache_lock.read().await;
                    if let Some((snap, cached_time)) = cache.get(&acc.id) {
                        if !auto_retrieval_allowed || (now - *cached_time < ttl) {
                            return snap.clone();
                        }
                    } else if !auto_retrieval_allowed {
                        return UsageSnapshot {
                            account_id: acc.id.clone(),
                            provider: acc.provider,
                            configured_email: acc.email.clone(),
                            observed_email: None,
                            status: AccountStatus::Cached,
                            error_code: ErrorCode::None,
                            message: Some("Auto-retrieval paused in preferences".to_string()),
                            source: acc.provider.as_str().to_string(),
                            plan_type: None,
                            observed_at: Some(now),
                            retrieved_at: Some(now),
                            windows: vec![],
                        };
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
            });
            tasks.push((task_account, handle));
        }

        let mut results = Vec::with_capacity(tasks.len());
        for (account, task) in tasks {
            match task.await {
                Ok(snap) => results.push(snap),
                Err(error) => {
                    tracing::error!(
                        account_id = %account.id,
                        provider = %account.provider,
                        %error,
                        "provider collection task failed"
                    );
                    let failed_at = Utc::now();
                    results.push(UsageSnapshot {
                        account_id: account.id.clone(),
                        provider: account.provider,
                        configured_email: account.email.clone(),
                        observed_email: None,
                        status: AccountStatus::Unavailable,
                        error_code: ErrorCode::UpstreamError,
                        message: Some("Provider task failed unexpectedly".to_string()),
                        source: account.provider.as_str().to_string(),
                        plan_type: None,
                        observed_at: Some(failed_at),
                        retrieved_at: Some(failed_at),
                        windows: vec![],
                    });
                }
            }
        }

        results
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AccountConfig, AutoRetrievalSettings};
    use async_trait::async_trait;

    struct PanicProvider;

    #[async_trait]
    impl UsageProvider for PanicProvider {
        async fn fetch(&self, _account: &AccountConfig) -> UsageSnapshot {
            panic!("simulated provider panic");
        }
    }

    #[tokio::test]
    async fn provider_task_panic_returns_unavailable_snapshot() {
        let mut providers: HashMap<ProviderName, Arc<dyn UsageProvider>> = HashMap::new();
        providers.insert(ProviderName::Codex, Arc::new(PanicProvider));
        let service = UsageService::new(providers);
        let settings = Settings {
            accounts: vec![AccountConfig {
                id: "codex-test".to_string(),
                provider: ProviderName::Codex,
                email: "test@example.com".to_string(),
                home: "/tmp".to_string(),
                priority: 0,
                warning_threshold: 80.0,
                critical_threshold: 95.0,
                auto_retrieval: true,
            }],
            auto_retrieval: AutoRetrievalSettings::default(),
        };

        let snapshots = service.collect(&settings, true).await;

        assert_eq!(snapshots.len(), 1);
        assert_eq!(snapshots[0].account_id, "codex-test");
        assert_eq!(snapshots[0].status, AccountStatus::Unavailable);
        assert_eq!(snapshots[0].error_code, ErrorCode::UpstreamError);
        assert_eq!(
            snapshots[0].message.as_deref(),
            Some("Provider task failed unexpectedly")
        );
    }
}
