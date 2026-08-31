use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ProviderName {
    Codex,
    Claude,
    Antigravity,
}

impl ProviderName {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
            Self::Antigravity => "antigravity",
        }
    }

    pub fn display_name(&self) -> &'static str {
        match self {
            Self::Codex => "Codex",
            Self::Claude => "Claude",
            Self::Antigravity => "Antigravity",
        }
    }
}

impl std::fmt::Display for ProviderName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AccountStatus {
    #[default]
    Live,
    Cached,
    Unavailable,
    RateLimited,
}

impl AccountStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Live => "live",
            Self::Cached => "cached",
            Self::Unavailable => "unavailable",
            Self::RateLimited => "rate_limited",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    #[default]
    None,
    NotAuthenticated,
    RateLimited,
    UpstreamError,
    IdentityMismatch,
    Timeout,
    NoRecentData,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AccountConfig {
    pub id: String,
    pub provider: ProviderName,
    pub email: String,
    pub home: String,
    #[serde(default)]
    pub priority: i32,
    #[serde(default = "default_warning_threshold")]
    pub warning_threshold: f64,
    #[serde(default = "default_critical_threshold")]
    pub critical_threshold: f64,
    #[serde(default = "default_true")]
    pub auto_retrieval: bool,
}

fn default_true() -> bool {
    true
}

fn default_warning_threshold() -> f64 {
    80.0
}

fn default_critical_threshold() -> f64 {
    95.0
}

impl AccountConfig {
    pub fn expanded_home(&self) -> String {
        if self.home.starts_with("~/") || self.home == "~" {
            if let Some(home_dir) = dirs::home_dir() {
                if self.home == "~" {
                    return home_dir.to_string_lossy().to_string();
                }
                return home_dir.join(&self.home[2..]).to_string_lossy().to_string();
            }
        }
        self.home.clone()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UsageWindow {
    pub id: String,
    pub used_percent: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window_minutes: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resets_at: Option<DateTime<Utc>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub raw_limits: Option<serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UsageSnapshot {
    pub account_id: String,
    pub provider: ProviderName,
    pub configured_email: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_email: Option<String>,
    pub status: AccountStatus,
    #[serde(default)]
    pub error_code: ErrorCode,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    pub source: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub plan_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_at: Option<DateTime<Utc>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retrieved_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub windows: Vec<UsageWindow>,
}

impl UsageSnapshot {
    pub fn max_used_percent(&self) -> Option<f64> {
        self.windows
            .iter()
            .map(|w| w.used_percent)
            .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AccountAnalytics {
    pub account_id: String,
    pub provider: ProviderName,
    pub current_percent: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub limiting_window_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub burn_rate_per_hour: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub minutes_to_exhaustion: Option<i64>,
    pub status: AccountStatus,
    #[serde(default)]
    pub recommended: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recommendation_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnalyticsResponse {
    pub generated_at: DateTime<Utc>,
    pub accounts: Vec<AccountAnalytics>,
    pub suggestions: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AutoRetrievalSettings {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_poll_interval_secs")]
    pub poll_interval_secs: u64,
    #[serde(default = "default_codex_ttl_secs")]
    pub codex_ttl_secs: u64,
    #[serde(default = "default_claude_ttl_secs")]
    pub claude_ttl_secs: u64,
    #[serde(default = "default_antigravity_ttl_secs")]
    pub antigravity_ttl_secs: u64,
}

fn default_poll_interval_secs() -> u64 {
    60
}

fn default_codex_ttl_secs() -> u64 {
    180
}

fn default_claude_ttl_secs() -> u64 {
    300
}

fn default_antigravity_ttl_secs() -> u64 {
    90
}

impl AutoRetrievalSettings {
    pub fn ttl_for_provider(&self, provider: &ProviderName) -> u64 {
        match provider {
            ProviderName::Codex => self.codex_ttl_secs,
            ProviderName::Claude => self.claude_ttl_secs,
            ProviderName::Antigravity => self.antigravity_ttl_secs,
        }
    }
}

impl Default for AutoRetrievalSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            poll_interval_secs: default_poll_interval_secs(),
            codex_ttl_secs: default_codex_ttl_secs(),
            claude_ttl_secs: default_claude_ttl_secs(),
            antigravity_ttl_secs: default_antigravity_ttl_secs(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct Settings {
    #[serde(default)]
    pub accounts: Vec<AccountConfig>,
    #[serde(default)]
    pub auto_retrieval: AutoRetrievalSettings,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LoginMethod {
    Browser,
    DeviceCode,
}

impl LoginMethod {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Browser => "browser",
            Self::DeviceCode => "device_code",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LoginStatus {
    Pending,
    Succeeded,
    Failed,
    Cancelled,
    Expired,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoginChallenge {
    pub attempt_id: String,
    pub method: LoginMethod,
    pub status: LoginStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auth_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub verification_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_code: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoginAttempt {
    pub attempt_id: String,
    pub account_id: String,
    pub method: LoginMethod,
    pub status: LoginStatus,
    pub started_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_email: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountStatusView {
    pub account_id: String,
    pub provider: ProviderName,
    pub configured_email: String,
    pub configured_home: String,
    pub ready: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_email: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HistoryPoint {
    pub account_id: String,
    pub provider: String,
    pub window_id: String,
    pub used_percent: f64,
    pub observed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HourlyUsageDistribution {
    pub hour: i32,
    pub average_percent: f64,
    pub samples_count: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_domain_serialization() {
        let snap = UsageSnapshot {
            account_id: "codex-primary".to_string(),
            provider: ProviderName::Codex,
            configured_email: "test@example.com".to_string(),
            observed_email: Some("test@example.com".to_string()),
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "codex_app_server".to_string(),
            plan_type: Some("pro".to_string()),
            observed_at: Some(Utc::now()),
            retrieved_at: Some(Utc::now()),
            windows: vec![UsageWindow {
                id: "primary".to_string(),
                used_percent: 42.5,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        };

        let json = serde_json::to_string(&snap).unwrap();
        assert!(json.contains("\"account_id\":\"codex-primary\""));
        assert!(json.contains("\"provider\":\"codex\""));
        assert!(json.contains("\"used_percent\":42.5"));

        let deserialized: UsageSnapshot = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.account_id, "codex-primary");
        assert_eq!(deserialized.windows[0].used_percent, 42.5);
    }

    #[test]
    fn account_config_defaults_critical_threshold_for_old_configs() {
        let config: AccountConfig = serde_json::from_str(
            r#"{"id":"codex-primary","provider":"codex","email":"a@example.com","home":"~/.codex","warning_threshold":80}"#,
        )
        .unwrap();
        assert_eq!(config.critical_threshold, 95.0);
    }
}
