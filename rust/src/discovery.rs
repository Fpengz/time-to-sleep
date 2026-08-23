use std::collections::HashSet;

use serde_json::Value;

use crate::domain::{AccountConfig, ProviderName};

pub fn discover_accounts(existing_ids: &[&str]) -> Vec<AccountConfig> {
    let existing_set: HashSet<&str> = existing_ids.iter().copied().collect();
    let mut discovered = Vec::new();

    let Some(home) = dirs::home_dir() else {
        return discovered;
    };

    // 1. Discover Codex accounts
    let codex_home = home.join(".codex");
    if codex_home.is_dir() {
        let auth_path = codex_home.join("auth.json");
        let mut email = "primary@codex".to_string();
        if auth_path.is_file() {
            if let Ok(content) = std::fs::read_to_string(&auth_path) {
                if let Ok(val) = serde_json::from_str::<Value>(&content) {
                    if let Some(e) = val.get("email").and_then(|v| v.as_str()) {
                        email = e.to_string();
                    }
                }
            }
        }

        if !existing_set.contains("codex-primary") && !existing_set.contains("codex") {
            discovered.push(AccountConfig {
                id: "codex-primary".to_string(),
                provider: ProviderName::Codex,
                email,
                home: "~/.codex".to_string(),
                priority: 0,
                warning_threshold: 80.0,
            });
        }
    }

    // 2. Discover Claude accounts
    let claude_json = home.join(".claude.json");
    let credentials_json = home.join(".credentials.json");
    if claude_json.is_file() || credentials_json.is_file() {
        let mut email = "primary@claude".to_string();
        if credentials_json.is_file() {
            if let Ok(content) = std::fs::read_to_string(&credentials_json) {
                if let Ok(val) = serde_json::from_str::<Value>(&content) {
                    if let Some(e) = val.pointer("/claudeAiOauth/email").and_then(|v| v.as_str()) {
                        email = e.to_string();
                    }
                }
            }
        }
        if !existing_set.contains("claude") {
            discovered.push(AccountConfig {
                id: "claude".to_string(),
                provider: ProviderName::Claude,
                email,
                home: "~".to_string(),
                priority: 0,
                warning_threshold: 80.0,
            });
        }
    }

    // 3. Discover Antigravity accounts
    let agy_dir = home.join(".gemini/antigravity-cli");
    if agy_dir.is_dir() {
        let mut email = "primary@antigravity".to_string();
        let auth_path = agy_dir.join("auth.json");
        if auth_path.is_file() {
            if let Ok(content) = std::fs::read_to_string(&auth_path) {
                if let Ok(val) = serde_json::from_str::<Value>(&content) {
                    if let Some(e) = val.get("email").and_then(|v| v.as_str()) {
                        email = e.to_string();
                    }
                }
            }
        }
        if !existing_set.contains("antigravity") {
            discovered.push(AccountConfig {
                id: "antigravity".to_string(),
                provider: ProviderName::Antigravity,
                email,
                home: "~/.gemini/antigravity-cli".to_string(),
                priority: 0,
                warning_threshold: 80.0,
            });
        }
    }

    discovered
}
