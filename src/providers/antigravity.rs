use std::sync::Mutex;
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use async_trait::async_trait;
use chrono::Utc;
use reqwest::Client;
use serde_json::{json, Value};
use tokio::process::Command;

use super::parsers::parse_antigravity_quota_summary;
use super::UsageProvider;
use crate::domain::{AccountConfig, AccountStatus, ErrorCode, ProviderName, UsageSnapshot};

#[derive(Debug, Clone)]
pub struct LocalServer {
    pub pid: u32,
    pub port: u16,
    pub csrf_token: Option<String>,
}

const NOT_FOUND_RECHECK_INTERVAL: Duration = Duration::from_secs(120);

pub struct AntigravityProvider {
    client: Client,
    cached_server: Mutex<Option<LocalServer>>,
    last_not_found: Mutex<Option<Instant>>,
}

impl Default for AntigravityProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl AntigravityProvider {
    pub fn new() -> Self {
        Self {
            client: Client::builder()
                .timeout(Duration::from_millis(1500))
                .danger_accept_invalid_certs(true)
                .build()
                .unwrap_or_default(),
            cached_server: Mutex::new(None),
            last_not_found: Mutex::new(None),
        }
    }

    pub async fn post_probe(&self, server: &LocalServer) -> bool {
        self.post_grpc_json(server, "GetUnleashData", &json!({}))
            .await
            .is_ok()
    }

    pub async fn post_grpc_json(
        &self,
        server: &LocalServer,
        method: &str,
        body: &Value,
    ) -> Result<Value> {
        let mut req_builder = self
            .client
            .post(format!(
                "http://127.0.0.1:{}/exa.language_server_pb.LanguageServerService/{}",
                server.port, method
            ))
            .header("Connect-Protocol-Version", "1")
            .header("Content-Type", "application/json");

        if let Some(ref csrf) = server.csrf_token {
            req_builder = req_builder.header("X-Codeium-Csrf-Token", csrf);
        }

        let resp = req_builder.json(body).send().await?;
        if resp.status().is_success() {
            let val = resp.json::<Value>().await?;
            Ok(val)
        } else {
            // Try https fallback
            let mut req_builder = self
                .client
                .post(format!(
                    "https://127.0.0.1:{}/exa.language_server_pb.LanguageServerService/{}",
                    server.port, method
                ))
                .header("Connect-Protocol-Version", "1")
                .header("Content-Type", "application/json");

            if let Some(ref csrf) = server.csrf_token {
                req_builder = req_builder.header("X-Codeium-Csrf-Token", csrf);
            }
            let resp = req_builder.json(body).send().await?;
            if resp.status().is_success() {
                let val = resp.json::<Value>().await?;
                Ok(val)
            } else {
                bail!("request failed with status {}", resp.status())
            }
        }
    }

    async fn find_server(&self) -> Option<LocalServer> {
        // Fast path: probe cached server
        let cached_opt = { self.cached_server.lock().unwrap().clone() };
        if let Some(ref s) = cached_opt {
            if self.post_probe(s).await {
                return Some(s.clone());
            }
        }
        {
            let mut cached = self.cached_server.lock().unwrap();
            *cached = None;
        }

        // The language server is very often just not running (Antigravity isn't the
        // user's active tool). Once we've confirmed that, skip the ps/lsof scan for a
        // while instead of re-scanning every poll.
        {
            let last_not_found = *self.last_not_found.lock().unwrap();
            if let Some(seen_at) = last_not_found {
                if seen_at.elapsed() < NOT_FOUND_RECHECK_INTERVAL {
                    return None;
                }
            }
        }

        if let Some(server) = self.scan_for_server().await {
            let mut cached = self.cached_server.lock().unwrap();
            *cached = Some(server.clone());
            return Some(server);
        }

        *self.last_not_found.lock().unwrap() = Some(Instant::now());
        None
    }

    async fn scan_for_server(&self) -> Option<LocalServer> {
        let output = Command::new("ps")
            .args(["-ax", "-o", "pid=,command="])
            .output()
            .await
            .ok()?;

        let ps_out = String::from_utf8_lossy(&output.stdout);
        for line in ps_out.lines() {
            let trimmed = line.trim();
            if !trimmed.contains("language_server") || !trimmed.contains("antigravity") {
                continue;
            }

            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            let Some(pid_str) = parts.first() else {
                continue;
            };
            let Ok(pid) = pid_str.parse::<u32>() else {
                continue;
            };

            let csrf_token = parts.iter().find_map(|arg| {
                if arg.starts_with("--csrf_token=") {
                    Some(arg.trim_start_matches("--csrf_token=").to_string())
                } else {
                    None
                }
            });

            // Find listening ports via lsof
            let lsof_out = Command::new("lsof")
                .args(["-nP", "-a", "-p", &pid.to_string(), "-iTCP", "-sTCP:LISTEN"])
                .output()
                .await
                .ok();

            if let Some(lsof) = lsof_out {
                let lsof_text = String::from_utf8_lossy(&lsof.stdout);
                for lsof_line in lsof_text.lines() {
                    if let Some(port_str) = lsof_line
                        .split(':')
                        .next_back()
                        .and_then(|s| s.split_whitespace().next())
                    {
                        if let Ok(port) = port_str.parse::<u16>() {
                            let s = LocalServer {
                                pid,
                                port,
                                csrf_token: csrf_token.clone(),
                            };
                            if self.post_probe(&s).await {
                                return Some(s);
                            }
                        }
                    }
                }
            }
        }

        None
    }
}

#[async_trait]
impl UsageProvider for AntigravityProvider {
    async fn fetch(&self, account: &AccountConfig) -> UsageSnapshot {
        let retrieved_at = Utc::now();
        let Some(server) = self.find_server().await else {
            return UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Antigravity,
                configured_email: account.email.clone(),
                observed_email: None,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::NoRecentData,
                message: Some("Antigravity language server is not running".to_string()),
                source: "antigravity".to_string(),
                plan_type: None,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            };
        };

        let status_res = self
            .post_grpc_json(&server, "GetUserStatus", &json!({}))
            .await;
        let mut observed_email = None;
        let mut plan_type = None;

        if let Ok(status_val) = status_res {
            observed_email = status_val
                .pointer("/userStatus/email")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            plan_type = status_val
                .pointer("/userStatus/planType")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
        }

        if let Some(ref obs_email) = observed_email {
            if !obs_email.eq_ignore_ascii_case(&account.email) {
                return UsageSnapshot {
                    account_id: account.id.clone(),
                    provider: ProviderName::Antigravity,
                    configured_email: account.email.clone(),
                    observed_email: Some(obs_email.clone()),
                    status: AccountStatus::Unavailable,
                    error_code: ErrorCode::IdentityMismatch,
                    message: Some(format!("Expected {}, found {}", account.email, obs_email)),
                    source: "antigravity_local_server".to_string(),
                    plan_type,
                    observed_at: Some(retrieved_at),
                    retrieved_at: Some(retrieved_at),
                    windows: vec![],
                };
            }
        }

        let quota_doc = match self
            .post_grpc_json(&server, "GetQuotaSummary", &json!({}))
            .await
        {
            Ok(doc) => doc,
            Err(e) => {
                return UsageSnapshot {
                    account_id: account.id.clone(),
                    provider: ProviderName::Antigravity,
                    configured_email: account.email.clone(),
                    observed_email,
                    status: AccountStatus::Unavailable,
                    error_code: ErrorCode::UpstreamError,
                    message: Some(format!("Failed to retrieve quota summary: {}", e)),
                    source: "antigravity_local_server".to_string(),
                    plan_type,
                    observed_at: Some(retrieved_at),
                    retrieved_at: Some(retrieved_at),
                    windows: vec![],
                };
            }
        };

        match parse_antigravity_quota_summary(&quota_doc) {
            Ok(parsed) => UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Antigravity,
                configured_email: account.email.clone(),
                observed_email,
                status: AccountStatus::Live,
                error_code: ErrorCode::None,
                message: None,
                source: "antigravity_local_server".to_string(),
                plan_type,
                observed_at: Some(parsed.observed_at),
                retrieved_at: Some(retrieved_at),
                windows: parsed.windows,
            },
            Err(e) => UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Antigravity,
                configured_email: account.email.clone(),
                observed_email,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::UpstreamError,
                message: Some(format!("Failed to parse quota summary: {}", e)),
                source: "antigravity_local_server".to_string(),
                plan_type,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            },
        }
    }
}
