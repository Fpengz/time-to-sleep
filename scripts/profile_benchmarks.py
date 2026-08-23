#!/usr/bin/env python3
"""
Performance & Efficiency Profiling Suite for Time-to-Sleep.

Measures CPU execution time, memory allocations (tracemalloc), query latencies,
and throughput across all core subsystems (storage, services, analytics, formatters).
"""

import cProfile
import io
import pstats
import time
import tracemalloc
from datetime import UTC, datetime, timedelta

from time_to_sleep.cli import format_prompt, format_table
from time_to_sleep.domain import (
    AccountConfig,
    AccountStatus,
    ProviderName,
    Settings,
    UsageSnapshot,
    UsageWindow,
)
from time_to_sleep.history import HistoryStore
from time_to_sleep.providers.base import UsageProvider
from time_to_sleep.services import AnalyticsService, ProviderRegistry, UsageService


def create_dummy_snapshots(count: int = 4) -> list[UsageSnapshot]:
    now = datetime.now(UTC)
    configs: list[tuple[str, ProviderName, str, float]] = [
        ("codex-primary", "codex", "wzf5350@gmail.com", 63.5),
        ("codex-secondary", "codex", "wzf0513@gmail.com", 12.0),
        ("claude", "claude", "wzf5350@gmail.com", 82.0),
        ("antigravity", "antigravity", "wzf5350@gmail.com", 5.0),
    ]
    snapshots = []
    for acc_id, prov, email, pct in configs[:count]:
        snapshots.append(
            UsageSnapshot(
                account_id=acc_id,
                provider=prov,
                configured_email=email,
                observed_email=email,
                status=AccountStatus.LIVE,
                source=f"{prov}_live",
                observed_at=now,
                retrieved_at=now,
                windows=[
                    UsageWindow(id="primary", used_percent=pct, window_minutes=300),
                    UsageWindow(
                        id="weekly",
                        used_percent=max(0.0, pct - 10),
                        window_minutes=10080,
                    ),
                ],
            )
        )
    return snapshots


class BenchmarkFakeProvider(UsageProvider):
    def __init__(self, snapshot: UsageSnapshot) -> None:
        self.snapshot = snapshot

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        return self.snapshot


def profile_storage() -> dict[str, str]:
    store = HistoryStore(":memory:")
    now = datetime.now(UTC)

    # 1. Ingestion of 1,000 snapshots with deduplication
    raw_snapshots = []
    for i in range(1000):
        t = now - timedelta(minutes=i * 10)
        raw_snapshots.append(
            UsageSnapshot(
                account_id="codex-primary",
                provider="codex",
                configured_email="test@example.com",
                status=AccountStatus.LIVE,
                source="test",
                retrieved_at=t,
                windows=[UsageWindow(id="primary", used_percent=(i * 2.3) % 100)],
            )
        )

    tracemalloc.start()
    t0 = time.perf_counter()
    store.record_snapshots(raw_snapshots)
    t1 = time.perf_counter()
    _, peak_ingest_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 2. Heatmap SQL aggregation over 100 queries
    t0_heat = time.perf_counter()
    for _ in range(100):
        _ = store.get_hourly_heatmap(account_id="codex-primary", days=7)
    t1_heat = time.perf_counter()

    # 3. 24h history retrieval over 100 queries
    t0_hist = time.perf_counter()
    for _ in range(100):
        _ = store.get_history(account_id="codex-primary", hours=24)
    t1_hist = time.perf_counter()

    ingest_str = f"{(t1 - t0) * 1000:.2f} ms (Peak RAM: {peak_ingest_mem / 1024:.1f} KB)"
    heat_avg = ((t1_heat - t0_heat) / 100) * 1000
    heat_str = f"{(t1_heat - t0_heat) * 1000:.2f} ms ({heat_avg:.3f} ms/query)"
    hist_avg = ((t1_hist - t0_hist) / 100) * 1000
    hist_str = f"{(t1_hist - t0_hist) * 1000:.2f} ms ({hist_avg:.3f} ms/query)"

    return {
        "Ingest 1k Records": ingest_str,
        "Heatmap SQL Aggregation (100x)": heat_str,
        "24h History Query (100x)": hist_str,
    }


def profile_analytics() -> dict[str, str]:
    analytics = AnalyticsService()
    snapshots = create_dummy_snapshots()
    settings = Settings(
        accounts=[
            AccountConfig(
                id=s.account_id,
                provider=s.provider,
                email=s.configured_email,
                home="/tmp",
            )
            for s in snapshots
        ]
    )

    t0 = time.perf_counter()
    for _ in range(1000):
        _ = analytics.analyze(snapshots, settings=settings)
    t1 = time.perf_counter()

    eval_avg = ((t1 - t0) / 1000) * 1000
    return {
        "Analytics & Routing (1k iterations)": f"{(t1 - t0) * 1000:.2f} ms ({eval_avg:.3f} ms/eval)"
    }


def profile_formatters() -> dict[str, str]:
    snapshots = create_dummy_snapshots()

    t0_prompt = time.perf_counter()
    for _ in range(10000):
        _ = format_prompt(snapshots, "compact")
    t1_prompt = time.perf_counter()

    t0_json = time.perf_counter()
    for _ in range(10000):
        _ = format_prompt(snapshots, "json")
    t1_json = time.perf_counter()

    t0_table = time.perf_counter()
    for _ in range(1000):
        _ = format_table(snapshots)
    t1_table = time.perf_counter()

    prompt_us = ((t1_prompt - t0_prompt) / 10000) * 1_000_000
    json_us = ((t1_json - t0_json) / 10000) * 1_000_000
    table_ms = ((t1_table - t0_table) / 1000) * 1000

    compact_str = f"{(t1_prompt - t0_prompt) * 1000:.2f} ms ({prompt_us:.2f} µs/call)"
    json_str = f"{(t1_json - t0_json) * 1000:.2f} ms ({json_us:.2f} µs/call)"
    table_str = f"{(t1_table - t0_table) * 1000:.2f} ms ({table_ms:.3f} ms/call)"

    return {
        "Compact Prompt Format (10k iterations)": compact_str,
        "JSON Prompt Format (10k iterations)": json_str,
        "CLI Table Format (1k iterations)": table_str,
    }


async def profile_service_cache() -> dict[str, str]:
    snapshots = create_dummy_snapshots()
    accounts = [
        AccountConfig(
            id=s.account_id,
            provider=s.provider,
            email=s.configured_email,
            home="/tmp",
        )
        for s in snapshots
    ]
    settings = Settings(accounts=accounts)
    registry = ProviderRegistry({s.provider: BenchmarkFakeProvider(s) for s in snapshots})
    service = UsageService(settings, registry)

    # Initial warm up
    await service.collect(force_refresh=True)

    # 1000 warm cache hits
    t0 = time.perf_counter()
    for _ in range(1000):
        await service.collect(force_refresh=False)
    t1 = time.perf_counter()

    collect_ms = ((t1 - t0) / 1000) * 1000
    cache_str = f"{(t1 - t0) * 1000:.2f} ms ({collect_ms:.3f} ms/collect)"
    return {"UsageService Warm Cache Hit (1k calls)": cache_str}


async def main_profile() -> None:
    print("═" * 70)
    print("      TIME-TO-SLEEP EFFICIENCY & PERFORMANCE PROFILING REPORT")
    print("═" * 70)

    # Run cProfile on full pipeline
    pr = cProfile.Profile()
    pr.enable()

    storage_res = profile_storage()
    analytics_res = profile_analytics()
    formatter_res = profile_formatters()
    service_res = await profile_service_cache()

    pr.disable()

    print("\n[1] SQLite Storage Engine & History")
    for k, v in storage_res.items():
        print(f"  • {k:<38} : {v}")

    print("\n[2] Analytics & Routing Engine")
    for k, v in analytics_res.items():
        print(f"  • {k:<38} : {v}")

    print("\n[3] Formatter & CLI Statusline")
    for k, v in formatter_res.items():
        print(f"  • {k:<38} : {v}")

    print("\n[4] Usage Retrieval & Cache Layer")
    for k, v in service_res.items():
        print(f"  • {k:<38} : {v}")

    # Top cProfile execution bottlenecks
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(8)
    print("\n[5] Top Cumulative CPU Hotspots (cProfile)")
    print("─" * 70)
    for line in s.getvalue().splitlines()[:14]:
        print("  " + line)
    print("═" * 70)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main_profile())
