import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from time_to_sleep.domain import UsageSnapshot


class HistoryPoint(BaseModel):
    account_id: str
    provider: str
    window_id: str
    used_percent: float
    observed_at: datetime


class HourlyUsageDistribution(BaseModel):
    hour: int
    average_percent: float
    samples_count: int


class HistoryStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None or db_path == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = str(Path(db_path).expanduser())
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._last_records: dict[tuple[str, str], tuple[float, datetime]] = {}
        self._last_prune: datetime = datetime.now(UTC)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    window_id TEXT NOT NULL,
                    used_percent REAL NOT NULL,
                    observed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_history_account_time 
                ON usage_history(account_id, observed_at)
                """
            )
            conn.commit()
        self.prune(max_days=30)

    def record_snapshots(self, snapshots: Sequence[UsageSnapshot]) -> None:
        now = datetime.now(UTC)
        if (now - self._last_prune).total_seconds() > 86400:
            self.prune(max_days=30)
            self._last_prune = now

        records: list[tuple[str, str, str, float, str]] = []

        for s in snapshots:
            ts_dt = s.retrieved_at or s.observed_at or now
            ts = ts_dt.isoformat()
            for w in s.windows:
                key = (s.account_id, w.id)
                if key in self._last_records:
                    last_pct, last_time = self._last_records[key]
                    if (
                        abs(w.used_percent - last_pct) < 0.001
                        and (ts_dt - last_time).total_seconds() < 300
                    ):
                        continue
                self._last_records[key] = (w.used_percent, ts_dt)
                records.append((s.account_id, s.provider, w.id, w.used_percent, ts))

        if not records:
            return

        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO usage_history (
                    account_id, provider, window_id, used_percent, observed_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    def get_history(
        self,
        account_id: str | None = None,
        hours: int = 24,
    ) -> list[HistoryPoint]:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        query = """
            SELECT account_id, provider, window_id, used_percent, observed_at
            FROM usage_history
            WHERE observed_at >= ?
        """
        params: list[Any] = [cutoff]

        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)

        query += " ORDER BY observed_at ASC"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        points: list[HistoryPoint] = []
        for r in rows:
            points.append(
                HistoryPoint(
                    account_id=r["account_id"],
                    provider=r["provider"],
                    window_id=r["window_id"],
                    used_percent=float(r["used_percent"]),
                    observed_at=datetime.fromisoformat(r["observed_at"]),
                )
            )
        return points

    def get_hourly_heatmap(
        self, account_id: str | None = None, days: int = 7
    ) -> list[HourlyUsageDistribution]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        query = """
            SELECT CAST(strftime('%H', observed_at) AS INTEGER) AS hr,
                   AVG(used_percent) AS avg_pct,
                   COUNT(*) AS sample_cnt
            FROM usage_history
            WHERE observed_at >= ?
        """
        params: list[Any] = [cutoff]
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)

        query += " GROUP BY hr"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = {row["hr"]: (row["avg_pct"], row["sample_cnt"]) for row in cursor.fetchall()}

        result: list[HourlyUsageDistribution] = []
        for h in range(24):
            if h in rows:
                avg, count = rows[h]
                result.append(
                    HourlyUsageDistribution(
                        hour=h,
                        average_percent=round(float(avg), 1),
                        samples_count=int(count),
                    )
                )
            else:
                result.append(
                    HourlyUsageDistribution(
                        hour=h,
                        average_percent=0.0,
                        samples_count=0,
                    )
                )
        return result

    def prune(self, max_days: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max_days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM usage_history WHERE observed_at < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
        return deleted


_default_history_path = Path("~/.config/time-to-sleep/history.db").expanduser()
default_history_store = HistoryStore(_default_history_path)
