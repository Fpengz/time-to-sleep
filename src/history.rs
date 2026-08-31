use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use anyhow::{Context, Result};
use chrono::{DateTime, Duration, Utc};
use rusqlite::{params, Connection};

use crate::domain::{HistoryPoint, HourlyUsageDistribution, UsageSnapshot};

type SnapshotCache = HashMap<(String, String), (f64, DateTime<Utc>)>;

pub struct HistoryStore {
    conn: Mutex<Connection>,
    last_records: Mutex<SnapshotCache>,
    last_prune: Mutex<DateTime<Utc>>,
}

impl HistoryStore {
    pub fn new(db_path: Option<&Path>) -> Result<Self> {
        let conn = match db_path {
            None => Connection::open_in_memory()?,
            Some(p) if p.to_str() == Some(":memory:") => Connection::open_in_memory()?,
            Some(p) => {
                if let Some(parent) = p.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                Connection::open(p)?
            }
        };

        // SQLite speed pragmas
        let _ = conn.execute_batch("PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;");

        let store = Self {
            conn: Mutex::new(conn),
            last_records: Mutex::new(HashMap::new()),
            last_prune: Mutex::new(Utc::now()),
        };

        store.init_db()?;
        let _ = store.prune(30);

        Ok(store)
    }

    pub fn default_path() -> PathBuf {
        if let Some(home) = dirs::home_dir() {
            home.join(".config/time-to-sleep/history.db")
        } else {
            PathBuf::from("history.db")
        }
    }

    fn init_db(&self) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS usage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                window_id TEXT NOT NULL,
                used_percent REAL NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_account_time
            ON usage_history(account_id, observed_at);
            CREATE INDEX IF NOT EXISTS idx_history_account_window_time
            ON usage_history(account_id, window_id, observed_at);
            ",
        )?;
        Ok(())
    }

    pub fn record_snapshots(&self, snapshots: &[UsageSnapshot]) -> Result<()> {
        let now = Utc::now();
        {
            let mut last_prune = self.last_prune.lock().unwrap();
            if (now - *last_prune).num_seconds() > 86400 {
                let _ = self.prune(30);
                *last_prune = now;
            }
        }

        let mut last_records = self.last_records.lock().unwrap();
        let mut pending_cache_updates: SnapshotCache = HashMap::new();
        let mut to_insert = Vec::new();

        for snapshot in snapshots {
            // Persist the time at which provider data was observed. Cached retrieval time is
            // only a fallback when the provider did not supply an observation timestamp.
            let ts = snapshot
                .observed_at
                .or(snapshot.retrieved_at)
                .unwrap_or(now);
            let ts_str = ts.to_rfc3339();

            for window in &snapshot.windows {
                let key = (snapshot.account_id.clone(), window.id.clone());
                let previous = pending_cache_updates
                    .get(&key)
                    .or_else(|| last_records.get(&key));

                if let Some((prev_pct, prev_time)) = previous {
                    let elapsed = (ts - *prev_time).num_seconds();
                    if elapsed < 0 {
                        // Do not let an out-of-order cached observation move history backward.
                        continue;
                    }
                    if (window.used_percent - *prev_pct).abs() < 0.001 && elapsed < 300 {
                        continue;
                    }
                }

                pending_cache_updates.insert(key, (window.used_percent, ts));
                to_insert.push((
                    snapshot.account_id.clone(),
                    snapshot.provider.as_str().to_string(),
                    window.id.clone(),
                    window.used_percent,
                    ts_str.clone(),
                ));
            }
        }

        if to_insert.is_empty() {
            return Ok(());
        }

        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT INTO usage_history (account_id, provider, window_id, used_percent, observed_at) VALUES (?, ?, ?, ?, ?)"
            )?;
            for (account_id, provider, window_id, used_percent, observed_at) in &to_insert {
                stmt.execute(params![
                    account_id,
                    provider,
                    window_id,
                    used_percent,
                    observed_at
                ])?;
            }
        }
        tx.commit()?;

        // The dedup cache represents successfully persisted state. Updating it only after the
        // transaction commits ensures a failed write can be retried immediately.
        last_records.extend(pending_cache_updates);
        Ok(())
    }

    fn history_point_from_row(row: &rusqlite::Row<'_>) -> Result<HistoryPoint> {
        let ts_str: String = row.get(4)?;
        let observed_at = DateTime::parse_from_rfc3339(&ts_str)
            .with_context(|| format!("invalid observed_at value in usage_history: {ts_str}"))?
            .with_timezone(&Utc);

        Ok(HistoryPoint {
            account_id: row.get(0)?,
            provider: row.get(1)?,
            window_id: row.get(2)?,
            used_percent: row.get(3)?,
            observed_at,
        })
    }

    pub fn get_history(&self, account_id: Option<&str>, hours: i64) -> Result<Vec<HistoryPoint>> {
        let cutoff = (Utc::now() - Duration::hours(hours)).to_rfc3339();
        let conn = self.conn.lock().unwrap();

        let mut query = "SELECT account_id, provider, window_id, used_percent, observed_at FROM usage_history WHERE observed_at >= ?".to_string();
        if account_id.is_some() {
            query.push_str(" AND account_id = ?");
        }
        query.push_str(" ORDER BY observed_at ASC");

        let mut stmt = conn.prepare(&query)?;
        let mut points = Vec::new();

        if let Some(acc_id) = account_id {
            let mut rows = stmt.query(params![cutoff, acc_id])?;
            while let Some(row) = rows.next()? {
                points.push(Self::history_point_from_row(row)?);
            }
        } else {
            let mut rows = stmt.query(params![cutoff])?;
            while let Some(row) = rows.next()? {
                points.push(Self::history_point_from_row(row)?);
            }
        }

        Ok(points)
    }

    pub fn get_hourly_heatmap(
        &self,
        account_id: Option<&str>,
        days: i64,
    ) -> Result<Vec<HourlyUsageDistribution>> {
        let cutoff = (Utc::now() - Duration::days(days)).to_rfc3339();
        let conn = self.conn.lock().unwrap();

        let mut query = "SELECT CAST(strftime('%H', observed_at) AS INTEGER) AS hr, AVG(used_percent) AS avg_pct, COUNT(*) AS sample_cnt FROM usage_history WHERE observed_at >= ?".to_string();
        if account_id.is_some() {
            query.push_str(" AND account_id = ?");
        }
        query.push_str(" GROUP BY hr");

        let mut stmt = conn.prepare(&query)?;
        let mut map: HashMap<i32, (f64, i64)> = HashMap::new();

        if let Some(acc_id) = account_id {
            let mut rows = stmt.query(params![cutoff, acc_id])?;
            while let Some(row) = rows.next()? {
                let hr: i32 = row.get(0)?;
                let avg: f64 = row.get(1)?;
                let count: i64 = row.get(2)?;
                map.insert(hr, (avg, count));
            }
        } else {
            let mut rows = stmt.query(params![cutoff])?;
            while let Some(row) = rows.next()? {
                let hr: i32 = row.get(0)?;
                let avg: f64 = row.get(1)?;
                let count: i64 = row.get(2)?;
                map.insert(hr, (avg, count));
            }
        };

        let mut result = Vec::with_capacity(24);
        for h in 0..24 {
            if let Some(&(avg, count)) = map.get(&h) {
                result.push(HourlyUsageDistribution {
                    hour: h,
                    average_percent: (avg * 10.0).round() / 10.0,
                    samples_count: count,
                });
            } else {
                result.push(HourlyUsageDistribution {
                    hour: h,
                    average_percent: 0.0,
                    samples_count: 0,
                });
            }
        }

        Ok(result)
    }

    pub fn prune(&self, max_days: i64) -> Result<usize> {
        let cutoff = (Utc::now() - Duration::days(max_days)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        let deleted = conn
            .execute(
                "DELETE FROM usage_history WHERE observed_at < ?",
                params![cutoff],
            )
            .context("Failed to prune usage history")?;
        Ok(deleted)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AccountStatus, ErrorCode, ProviderName, UsageWindow};

    #[test]
    fn test_history_dedup_and_heatmap() {
        let store = HistoryStore::new(None).unwrap();
        let now = Utc::now();

        let snap = UsageSnapshot {
            account_id: "codex-primary".to_string(),
            provider: ProviderName::Codex,
            configured_email: "test@example.com".to_string(),
            observed_email: None,
            status: AccountStatus::Live,
            error_code: ErrorCode::None,
            message: None,
            source: "test".to_string(),
            plan_type: None,
            observed_at: Some(now),
            retrieved_at: Some(now),
            windows: vec![UsageWindow {
                id: "primary".to_string(),
                used_percent: 50.0,
                window_minutes: Some(300),
                resets_at: None,
                raw_limits: None,
            }],
        };

        // First insert
        store.record_snapshots(&[snap.clone()]).unwrap();
        // Duplicate should be skipped
        store.record_snapshots(&[snap.clone()]).unwrap();

        let history = store.get_history(Some("codex-primary"), 24).unwrap();
        assert_eq!(history.len(), 1);

        let heatmap = store.get_hourly_heatmap(Some("codex-primary"), 7).unwrap();
        assert_eq!(heatmap.len(), 24);
        let hr = now.format("%H").to_string().parse::<i32>().unwrap();
        let entry = heatmap.iter().find(|h| h.hour == hr).unwrap();
        assert_eq!(entry.average_percent, 50.0);
        assert_eq!(entry.samples_count, 1);
    }
}
