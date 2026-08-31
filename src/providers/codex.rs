use std::path::{Path, PathBuf};
use std::process::Stdio;

use anyhow::{bail, Result};
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::time::{timeout, Duration};

use super::parsers::parse_codex_rollout;
use super::UsageProvider;
use crate::domain::{
    AccountConfig, AccountStatus, ErrorCode, ProviderName, UsageSnapshot, UsageWindow,
};

/// GUI-launched processes (Dock, Login Items, `open -a`) get a bare
/// `/usr/bin:/bin:/usr/sbin:/sbin` PATH with none of the locations a
/// Node-installed `codex` CLI typically lives in, so a plain
/// `Command::new("codex")` fails with ENOENT outside a terminal. Build an
/// explicit PATH covering common install locations (including every nvm
/// node version, since the active one isn't known ahead of time) so the
/// subprocess spawn works the same regardless of how the app was launched.
pub fn extended_path_env() -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Ok(existing) = std::env::var("PATH") {
        if !existing.is_empty() {
            parts.push(existing);
        }
    }
    if let Some(home) = dirs::home_dir() {
        if let Ok(entries) = std::fs::read_dir(home.join(".nvm/versions/node")) {
            for entry in entries.flatten() {
                let bin = entry.path().join("bin");
                if bin.is_dir() {
                    parts.push(bin.to_string_lossy().to_string());
                }
            }
        }
        parts.push(home.join(".local/bin").to_string_lossy().to_string());
        parts.push(home.join(".cargo/bin").to_string_lossy().to_string());
    }
    for p in [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ] {
        parts.push(p.to_string());
    }
    parts.join(":")
}

pub struct CodexProvider {
    command: String,
    timeout_duration: Duration,
}

impl Default for CodexProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl CodexProvider {
    pub fn new() -> Self {
        Self {
            command: "codex".to_string(),
            timeout_duration: Duration::from_secs(12),
        }
    }

    async fn fetch_via_app_server(&self, account: &AccountConfig) -> Result<UsageSnapshot> {
        let expanded_home = account.expanded_home();
        let mut child = Command::new(&self.command)
            .arg("app-server")
            .env("CODEX_HOME", &expanded_home)
            .env("PATH", extended_path_env())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;

        let mut stdin = child.stdin.take().context("failed to open stdin")?;
        let stdout = child.stdout.take().context("failed to open stdout")?;
        let mut reader = BufReader::new(stdout).lines();

        // 1. Send initialize
        let init_req = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "time-to-sleep", "version": "0.1.0"}}
        });
        stdin
            .write_all(format!("{}\n", init_req).as_bytes())
            .await?;

        // 2. Send account/read
        let account_req = json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "account/read",
            "params": {}
        });
        stdin
            .write_all(format!("{}\n", account_req).as_bytes())
            .await?;

        // 3. Send account/rateLimits/read
        let limits_req = json!({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "account/rateLimits/read",
            "params": {}
        });
        stdin
            .write_all(format!("{}\n", limits_req).as_bytes())
            .await?;

        let mut account_data: Option<Value> = None;
        let mut rate_limits_data: Option<Value> = None;

        let read_loop = async {
            while let Ok(Some(line)) = reader.next_line().await {
                if let Ok(msg) = serde_json::from_str::<Value>(&line) {
                    if msg.get("id") == Some(&json!(2)) {
                        account_data = msg.get("result").and_then(|r| r.get("account")).cloned();
                    } else if msg.get("id") == Some(&json!(3)) {
                        rate_limits_data =
                            msg.get("result").and_then(|r| r.get("rateLimits")).cloned();
                    }
                    if account_data.is_some() && rate_limits_data.is_some() {
                        break;
                    }
                }
            }
        };

        let _ = timeout(self.timeout_duration, read_loop).await;
        let _ = child.kill().await;

        let retrieved_at = Utc::now();

        let Some(acc_obj) = account_data.as_ref().and_then(|v| v.as_object()) else {
            return Ok(UsageSnapshot {
                account_id: account.id.clone(),
                provider: ProviderName::Codex,
                configured_email: account.email.clone(),
                observed_email: None,
                status: AccountStatus::Unavailable,
                error_code: ErrorCode::NotAuthenticated,
                message: Some("Not logged in; run login to authenticate".to_string()),
                source: "codex_app_server".to_string(),
                plan_type: None,
                observed_at: Some(retrieved_at),
                retrieved_at: Some(retrieved_at),
                windows: vec![],
            });
        };
        let observed_email = acc_obj
            .get("email")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let plan_type = acc_obj
            .get("planType")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let mut windows = Vec::new();
        if let Some(limits) = rate_limits_data.and_then(|v| v.as_object().cloned()) {
            for (key, val) in limits {
                if (key == "primary" || key == "secondary") && val.is_object() {
                    let used = val
                        .get("usedPercent")
                        .or_else(|| val.get("used_percent"))
                        .and_then(|v| v.as_f64())
                        .unwrap_or(0.0);
                    let duration = val
                        .get("windowDurationMins")
                        .or_else(|| val.get("window_minutes"))
                        .and_then(|v| v.as_i64());
                    let resets_at = val
                        .get("resetsAt")
                        .or_else(|| val.get("resets_at"))
                        .and_then(|v| super::parsers::parse_timestamp(v, false).ok());

                    windows.push(UsageWindow {
                        id: key,
                        used_percent: used,
                        window_minutes: duration,
                        resets_at,
                        raw_limits: None,
                    });
                }
            }
        }

        Ok(UsageSnapshot {
            account_id: account.id.clone(),
            provider: ProviderName::Codex,
            configured_email: account.email.clone(),
            observed_email,
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "codex_app_server".to_string(),
            plan_type,
            observed_at: Some(retrieved_at),
            retrieved_at: Some(retrieved_at),
            windows,
        })
    }

    fn read_rollout_fallback(&self, home: &Path) -> Result<UsageSnapshot> {
        let mut candidate_files = Vec::new();
        for dir_name in ["sessions", "archived_sessions"] {
            let base = home.join(dir_name);
            if !base.is_dir() {
                continue;
            }
            Self::collect_jsonl_files(&base, &mut candidate_files, 0, 4);
        }

        candidate_files.sort_by_key(|p| std::fs::metadata(p).and_then(|m| m.modified()).ok());
        candidate_files.reverse();

        for path in candidate_files.iter().take(15) {
            if let Ok(content) = std::fs::read_to_string(path) {
                let lines: Vec<&str> = content.lines().collect();
                if let Ok(parsed) = parse_codex_rollout(&lines) {
                    return Ok(UsageSnapshot {
                        account_id: "".to_string(),
                        provider: ProviderName::Codex,
                        configured_email: "".to_string(),
                        observed_email: None,
                        status: AccountStatus::Cached,
                        error_code: ErrorCode::Timeout,
                        message: Some("Using local rollout fallback".to_string()),
                        source: "codex_rollout_fallback".to_string(),
                        plan_type: None,
                        observed_at: Some(parsed.observed_at),
                        retrieved_at: Some(Utc::now()),
                        windows: parsed.windows,
                    });
                }
            }
        }

        bail!("no Codex rollout snapshot found")
    }

    fn collect_jsonl_files(dir: &Path, out: &mut Vec<PathBuf>, depth: usize, max_depth: usize) {
        if depth > max_depth || out.len() >= 50 {
            return;
        }
        let Ok(entries) = std::fs::read_dir(dir) else {
            return;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                Self::collect_jsonl_files(&path, out, depth + 1, max_depth);
            } else if path.extension().and_then(|s| s.to_str()) == Some("jsonl") {
                out.push(path);
                if out.len() >= 50 {
                    break;
                }
            }
        }
    }
}

use anyhow::Context;

#[async_trait]
impl UsageProvider for CodexProvider {
    async fn fetch(&self, account: &AccountConfig) -> UsageSnapshot {
        match self.fetch_via_app_server(account).await {
            Ok(snap) => snap,
            Err(_) => {
                let expanded_home = PathBuf::from(account.expanded_home());
                if let Ok(mut snap) = self.read_rollout_fallback(&expanded_home) {
                    snap.account_id = account.id.clone();
                    snap.configured_email = account.email.clone();
                    return snap;
                }
                UsageSnapshot {
                    account_id: account.id.clone(),
                    provider: ProviderName::Codex,
                    configured_email: account.email.clone(),
                    observed_email: None,
                    status: AccountStatus::Unavailable,
                    error_code: ErrorCode::NotAuthenticated,
                    message: Some("Failed to retrieve Codex quota".to_string()),
                    source: "codex".to_string(),
                    plan_type: None,
                    observed_at: Some(Utc::now()),
                    retrieved_at: Some(Utc::now()),
                    windows: vec![],
                }
            }
        }
    }
}
