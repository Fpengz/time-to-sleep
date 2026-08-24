use serde_json::json;

use crate::domain::UsageSnapshot;

pub fn format_prompt(snapshots: &[UsageSnapshot], format_type: &str) -> String {
    if snapshots.is_empty() {
        if format_type == "json" {
            return json!({
                "accounts": [],
                "max_used_percent": 0.0,
                "needs_attention": false
            })
            .to_string();
        } else if format_type == "waybar" {
            return json!({
                "text": "No accounts",
                "tooltip": "No accounts configured",
                "class": "empty",
                "percentage": 0
            })
            .to_string();
        }
        return String::new();
    }

    let need_json = format_type == "json" || format_type == "waybar";
    let mut accounts_data = if need_json { Some(Vec::new()) } else { None };
    let mut parts = Vec::new();
    let mut max_pct = 0.0f64;
    let mut needs_attention = false;

    for s in snapshots {
        let base_name = match s.provider {
            crate::domain::ProviderName::Codex => "Codex",
            crate::domain::ProviderName::Claude => "Claude",
            crate::domain::ProviderName::Antigravity => "AGY",
        };
        let mut name = base_name.to_string();
        if snapshots.len() > 1 && s.account_id.ends_with("-secondary") {
            name.push('2');
        }

        if s.status != crate::domain::AccountStatus::Live {
            needs_attention = true;
            parts.push(format!("{}:!", name));
            if let Some(ref mut acc_list) = accounts_data {
                acc_list.push(json!({
                    "account_id": s.account_id,
                    "provider": s.provider.as_str(),
                    "status": s.status.as_str(),
                    "used_percent": 0.0,
                    "email": s.configured_email
                }));
            }
            continue;
        }

        if s.windows.is_empty() {
            parts.push(format!("{}:0%", name));
            if let Some(ref mut acc_list) = accounts_data {
                acc_list.push(json!({
                    "account_id": s.account_id,
                    "provider": s.provider.as_str(),
                    "status": s.status.as_str(),
                    "used_percent": 0.0,
                    "email": s.configured_email
                }));
            }
            continue;
        }

        let max_w = s
            .windows
            .iter()
            .max_by(|a, b| {
                a.used_percent
                    .partial_cmp(&b.used_percent)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .unwrap();
        let pct = max_w.used_percent;
        if pct > max_pct {
            max_pct = pct;
        }
        let rounded = pct.round() as i64;
        parts.push(format!("{}:{}%", name, rounded));

        if let Some(ref mut acc_list) = accounts_data {
            acc_list.push(json!({
                "account_id": s.account_id,
                "provider": s.provider.as_str(),
                "status": s.status.as_str(),
                "used_percent": pct,
                "email": s.configured_email
            }));
        }
    }

    let joined = parts.join(" | ");

    if format_type == "json" {
        return serde_json::to_string_pretty(&json!({
            "accounts": accounts_data,
            "max_used_percent": max_pct,
            "needs_attention": needs_attention,
            "summary": joined
        }))
        .unwrap_or_default();
    }

    if format_type == "waybar" {
        let status_class = if max_pct >= 90.0 {
            "critical"
        } else if max_pct >= 80.0 {
            "warning"
        } else {
            "normal"
        };
        let mut tooltip_lines = Vec::new();
        for s in snapshots {
            let pct = s.max_used_percent().unwrap_or(0.0);
            tooltip_lines.push(format!(
                "{} ({}): {:.1}% [{}]",
                s.provider.display_name(),
                s.account_id,
                pct,
                s.status.as_str()
            ));
        }
        return json!({
            "text": joined,
            "tooltip": tooltip_lines.join("\n"),
            "class": status_class,
            "percentage": max_pct.round() as i64
        })
        .to_string();
    }

    if format_type == "sketchybar" {
        let icon = if max_pct < 80.0 { "󰚩" } else { "" };
        return format!("{} {}", icon, joined);
    }

    if format_type == "starship" || format_type == "compact" {
        format!("[{}]", joined)
    } else if format_type == "tmux" {
        format!("#[fg=cyan]{}#[default]", joined)
    } else {
        joined
    }
}

pub fn format_table(snapshots: &[UsageSnapshot]) -> String {
    if snapshots.is_empty() {
        return "No accounts configured. Run `time-to-sleep discover` to get started.\n"
            .to_string();
    }

    let mut out = String::new();
    out.push_str(
        "╭───────────────────┬──────────────┬──────────────┬──────────────┬────────────────╮\n",
    );
    out.push_str(
        "│ Account           │ Provider     │ Status       │ Max Usage    │ Meter          │\n",
    );
    out.push_str(
        "├───────────────────┼──────────────┼──────────────┼──────────────┼────────────────┤\n",
    );

    for s in snapshots {
        let acc_name = if s.account_id.len() > 17 {
            format!("{}...", &s.account_id[..14])
        } else {
            s.account_id.clone()
        };

        let prov = s.provider.display_name();
        let status = s.status.as_str();
        let max_pct = s.max_used_percent().unwrap_or(0.0);
        let pct_str = format!("{:.1}%", max_pct);
        let meter = draw_progress_bar(max_pct, 14);

        out.push_str(&format!(
            "│ {:<17} │ {:<12} │ {:<12} │ {:>12} │ {} │\n",
            acc_name, prov, status, pct_str, meter
        ));
    }

    out.push_str(
        "╰───────────────────┴──────────────┴──────────────┴──────────────┴────────────────╯\n",
    );
    out
}

fn draw_progress_bar(percent: f64, width: usize) -> String {
    let clamped = (percent.clamp(0.0, 100.0) / 100.0) * (width as f64);
    let filled = clamped.round() as usize;
    let empty = width.saturating_sub(filled);

    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(empty));
    if percent >= 90.0 {
        format!("\x1b[31;1m{}\x1b[0m", bar)
    } else if percent >= 75.0 {
        format!("\x1b[33m{}\x1b[0m", bar)
    } else {
        format!("\x1b[32m{}\x1b[0m", bar)
    }
}
