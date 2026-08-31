use std::path::PathBuf;

use anyhow::Result;

use crate::discovery::discover_accounts;
use crate::domain::Settings;

pub fn settings_path() -> PathBuf {
    if let Ok(override_dir) = std::env::var("TIME_TO_SLEEP_CONFIG_DIR") {
        return PathBuf::from(override_dir).join("settings.json");
    }
    if let Some(home) = dirs::home_dir() {
        home.join(".config/time-to-sleep/settings.json")
    } else {
        PathBuf::from("settings.json")
    }
}

pub fn load_settings() -> Settings {
    let path = settings_path();
    if path.is_file() {
        if let Ok(content) = std::fs::read_to_string(&path) {
            if let Ok(settings) = serde_json::from_str::<Settings>(&content) {
                return settings;
            }
        }
    }

    // Try fallback config.json
    let fallback = path.with_file_name("config.json");
    if fallback.is_file() {
        if let Ok(content) = std::fs::read_to_string(&fallback) {
            if let Ok(settings) = serde_json::from_str::<Settings>(&content) {
                return settings;
            }
        }
    }

    // Auto-discover accounts
    let discovered = discover_accounts(&[]);
    let settings = Settings {
        accounts: discovered,
        ..Default::default()
    };
    let _ = save_settings(&settings);
    settings
}

pub fn save_settings(settings: &Settings) -> Result<()> {
    let path = settings_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(settings)?;
    std::fs::write(path, content)?;
    Ok(())
}
