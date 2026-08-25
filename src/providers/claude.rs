use std::path::PathBuf;
use std::sync::Mutex;

use async_trait::async_trait;
use chrono::Utc;
use reqwest::Client;
use serde_json::Value;

use super::UsageProvider;
use crate::domain::{
    AccountConfig, AccountStatus, ErrorCode, ProviderName, UsageSnapshot, UsageWindow,
};

const CLAUDE_USAGE_URL: &str = "https://api.anthropic.com/api/oauth/usage";

pub struct ClaudeProvider {
    client: Client,
    cached_token: Mutex<Option<String>>,
}

impl Default for ClaudeProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl ClaudeProvider {
    pub fn new() -> Self {
        Self {
            client: Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .build()
                .unwrap_or_default(),
            cached_token: Mutex::new(None),
        }
    }

    pub async fn get_token(&self, home: &str) -> Option<String> {
        if let Ok(env_tok) = std::env::var("CLAUDE_CODE_OAUTH_TOKEN") {
            let trimmed = env_tok.trim().to_string();
            if !trimmed.is_empty() {
                return Some(trimmed);
            }
        }

        {
            let cached = self.cached_token.lock().unwrap();
            if let Some(ref t) = *cached {
                return Some(t.clone());
            }
        }

        // Try reading from keychain on macOS
        if let Some(token) = Self::read_keychain().await {
            let mut cached = self.cached_token.lock().unwrap();
            *cached = Some(token.clone());
            return Some(token);
        }

        // Try ~/.credentials.json
        let cred_path = PathBuf::from(home).join(".credentials.json");
        if cred_path.is_file() {
            if let Ok(content) = std::fs::read_to_string(&cred_path) {
                if let Some(token) = Self::extract_token(&content) {
                    let mut cached = self.cached_token.lock().unwrap();
                    *cached = Some(token.clone());
                    return Some(token);
                }
            }
        }

        None
    }

    pub fn invalidate(&self) {
        let mut cached = self.cached_token.lock().unwrap();
        *cached = None;
    }

    async fn read_keychain() -> Option<String> {
        let username = std::env::var("USER").ok()?;
        let output = tokio::process::Command::new("security")
            .args([
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-a",
                &username,
                "-w",
            ])
            .output()
            .await
            .ok()?;

        if output.status.success() {
            let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
            Self::extract_token(&raw)
        } else {
            None
        }
    }

    fn extract_token(raw: &str) -> Option<String> {
        if raw.is_empty() {
            return None;
        }
        if let Ok(val) = serde_json::from_str::<Value>(raw) {
            if let Some(tok) = val
                .pointer("/claudeAiOauth/accessToken")
                .and_then(|v| v.as_str())
            {
                let trimmed = tok.trim().to_string();
                if !trimmed.is_empty() {
                    return Some(trimmed);
                }
            }
        }
        Some(raw.to_string())
    }
}

#[async_trait]
impl UsageProvider for ClaudeProvider {
    async fn fetch(&self, account: &AccountConfig) -> UsageSnapshot {
        let retrieved_at = Utc::now();
        let expanded_home = account.expanded_home();
        let Some(token) = self.get_token(&expanded_home).await else {
            return UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Claude,
                configured_email: account.email.clone(),
                observed_email: None,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::NotAuthenticated,
                message: Some("No Claude OAuth credential available".to_string()),
                source: "claude_oauth".to_string(),
                plan_type: None,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            };
        };

        let response = match self
            .client
            .get(CLAUDE_USAGE_URL)
            .header("Authorization", format!("Bearer {}", token))
            .header("anthropic-beta", "oauth-2025-04-20")
            .send()
            .await
        {
            Ok(r) => r,
            Err(e) => {
                return UsageSnapshot {
                    account_id: account.id.clone(),
                    provider: ProviderName::Claude,
                    configured_email: account.email.clone(),
                    observed_email: None,
                    status: AccountStatus::Unavailable,
                    error_code: ErrorCode::UpstreamError,
                    message: Some(format!("Request failed: {}", e)),
                    source: "claude_oauth".to_string(),
                    plan_type: None,
                    observed_at: Some(retrieved_at),
                    retrieved_at: Some(retrieved_at),
                    windows: vec![],
                };
            }
        };

        if response.status() == reqwest::StatusCode::UNAUTHORIZED {
            self.invalidate();
            return UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Claude,
                configured_email: account.email.clone(),
                observed_email: None,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::NotAuthenticated,
                message: Some("Claude credential expired; run claude auth login".to_string()),
                source: "claude_oauth".to_string(),
                plan_type: None,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            };
        }

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            let detail = body.chars().take(200).collect::<String>();
            return UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Claude,
                configured_email: account.email.clone(),
                observed_email: None,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::UpstreamError,
                message: Some(if detail.is_empty() {
                    format!("HTTP error {}", status)
                } else {
                    format!("HTTP error {}: {}", status, detail)
                }),
                source: "claude_oauth".to_string(),
                plan_type: None,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            };
        }

        let doc: Value = match response.json().await {
            Ok(d) => d,
            Err(e) => {
                return UsageSnapshot {
                    account_id: account.id.clone(),
                    provider: ProviderName::Claude,
                    configured_email: account.email.clone(),
                    observed_email: None,
                    status: AccountStatus::Unavailable,
                    error_code: ErrorCode::UpstreamError,
                    message: Some(format!("Failed to parse response: {}", e)),
                    source: "claude_oauth".to_string(),
                    plan_type: None,
                    observed_at: Some(retrieved_at),
                    retrieved_at: Some(retrieved_at),
                    windows: vec![],
                };
            }
        };

        let mut windows = Vec::new();
        for (window_id, minutes) in [("five_hour", 300), ("seven_day", 10080)] {
            let Some(raw) = doc.get(window_id) else {
                continue;
            };
            let Some(used) = raw
                .get("utilization")
                .or_else(|| raw.get("used_percentage"))
                .and_then(|v| v.as_f64())
            else {
                continue;
            };
            let resets_at = raw
                .get("resets_at")
                .and_then(|v| super::parsers::parse_timestamp(v, false).ok());
            windows.push(UsageWindow {
                id: window_id.to_string(),
                used_percent: used,
                window_minutes: Some(minutes),
                resets_at,
                raw_limits: None,
            });
        }

        UsageSnapshot {
            account_id: account.id.clone(),
            provider: ProviderName::Claude,
            configured_email: account.email.clone(),
            observed_email: Some(account.email.clone()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "claude_oauth".to_string(),
            plan_type: Some("claude_code".to_string()),
            observed_at: Some(retrieved_at),
            retrieved_at: Some(retrieved_at),
            windows,
        }
    }
}
