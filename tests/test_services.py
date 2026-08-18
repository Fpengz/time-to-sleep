from datetime import UTC, datetime, timedelta

import pytest

from time_to_sleep.domain import (
    AccountConfig,
    AccountStatus,
    ErrorCode,
    ProviderName,
    Settings,
    UsageSnapshot,
    UsageWindow,
)
from time_to_sleep.services import ProviderRegistry, UsageCache, UsageService


def account(account_id: str, provider: ProviderName) -> AccountConfig:
    return AccountConfig(
        id=account_id,
        provider=provider,
        email=f"{account_id}@example.com",
        home="/tmp/provider-home",
    )


def snapshot(config: AccountConfig, now: datetime) -> UsageSnapshot:
    return UsageSnapshot(
        account_id=config.id,
        provider=config.provider,
        configured_email=config.email,
        observed_email=config.email,
        status=AccountStatus.LIVE,
        source=f"{config.provider}_test",
        observed_at=now,
        retrieved_at=now,
        windows=[UsageWindow(id="primary", used_percent=10, window_minutes=300)],
    )


class FakeProvider:
    def __init__(self, result: UsageSnapshot | Exception) -> None:
        self.result = result
        self.calls = 0

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_usage_service_reuses_live_result_inside_provider_ttl() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    codex = account("codex", "codex")
    provider = FakeProvider(snapshot(codex, now))
    service = UsageService(
        Settings(accounts=[codex]),
        ProviderRegistry({"codex": provider}),
        cache=UsageCache(),
        now=lambda: now,
    )

    first = await service.collect()
    second = await service.collect()

    assert first[0].status is AccountStatus.LIVE
    assert second[0].status is AccountStatus.LIVE
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_usage_service_force_refresh_bypasses_cache() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    codex = account("codex", "codex")
    provider = FakeProvider(snapshot(codex, now))
    service = UsageService(
        Settings(accounts=[codex]),
        ProviderRegistry({"codex": provider}),
        cache=UsageCache(),
        now=lambda: now,
    )

    await service.collect()
    await service.collect(force_refresh=True)

    assert provider.calls == 2


@pytest.mark.asyncio
async def test_usage_service_keeps_siblings_when_one_provider_fails() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    codex = account("codex", "codex")
    claude = account("claude", "claude")
    good = FakeProvider(snapshot(codex, now))
    bad = FakeProvider(RuntimeError("provider down"))
    service = UsageService(
        Settings(accounts=[codex, claude]),
        ProviderRegistry({"codex": good, "claude": bad}),
        cache=UsageCache(),
        now=lambda: now,
    )

    results = await service.collect()

    assert [result.status for result in results] == [AccountStatus.LIVE, AccountStatus.UNAVAILABLE]
    assert results[1].error_code is ErrorCode.NOT_AUTHENTICATED


@pytest.mark.asyncio
async def test_usage_service_marks_expired_cached_result_stale() -> None:
    old = datetime(2026, 8, 17, tzinfo=UTC)
    now = old + timedelta(hours=2)
    codex = account("codex", "codex")
    provider = FakeProvider(snapshot(codex, old))
    service = UsageService(
        Settings(accounts=[codex]),
        ProviderRegistry({"codex": provider}),
        cache=UsageCache(),
        now=lambda: now,
    )

    await service.collect()
    provider.result = RuntimeError("provider down")
    results = await service.collect(force_refresh=True)

    assert results[0].status is AccountStatus.STALE
    assert results[0].error_code is ErrorCode.NOT_AUTHENTICATED
