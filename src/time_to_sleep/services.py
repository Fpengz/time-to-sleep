import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from time_to_sleep.domain import (
    AccountConfig,
    AccountStatus,
    ErrorCode,
    Settings,
    UsageSnapshot,
)
from time_to_sleep.providers.base import UsageProvider

DEFAULT_TTLS = {
    "codex": timedelta(seconds=60),
    "claude": timedelta(minutes=5),
    "antigravity": timedelta(0),
}
DEFAULT_TIMEOUTS = {
    "codex": 15.0,
    "claude": 15.0,
    "antigravity": 5.0,
}
FALLBACK_GRACE = timedelta(minutes=15)


class ProviderRegistry:
    def __init__(self, providers: Mapping[str, UsageProvider]) -> None:
        self._providers = dict(providers)

    def get(self, provider: str) -> UsageProvider | None:
        return self._providers.get(provider)


class UsageCache:
    def __init__(self) -> None:
        self._snapshots: dict[str, UsageSnapshot] = {}

    def get(self, account_id: str) -> UsageSnapshot | None:
        return self._snapshots.get(account_id)

    def put(self, snapshot: UsageSnapshot) -> None:
        self._snapshots[snapshot.account_id] = snapshot

    def clear(self) -> None:
        self._snapshots.clear()


class UsageService:
    def __init__(
        self,
        settings: Settings,
        providers: ProviderRegistry,
        *,
        cache: UsageCache | None = None,
        now: Callable[[], datetime] | None = None,
        ttls: Mapping[str, timedelta] | None = None,
        timeouts: Mapping[str, float] | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.cache = cache or UsageCache()
        self._now = now or (lambda: datetime.now(UTC))
        self._ttls = {**DEFAULT_TTLS, **(ttls or {})}
        self._timeouts = {**DEFAULT_TIMEOUTS, **(timeouts or {})}

    async def collect(self, *, force_refresh: bool = False) -> list[UsageSnapshot]:
        results = await asyncio.gather(
            *(
                self._collect_one(account, force_refresh=force_refresh)
                for account in self.settings.accounts
            )
        )
        return list(results)

    async def _collect_one(self, account: AccountConfig, *, force_refresh: bool) -> UsageSnapshot:
        now = self._now()
        cached = self.cache.get(account.id)
        if not force_refresh and self._is_fresh(cached, account.provider, now):
            assert cached is not None
            return cached

        provider = self.providers.get(account.provider)
        if provider is None:
            return self._failure_snapshot(
                account,
                cached,
                now,
                ErrorCode.NOT_CONFIGURED,
                f"No provider adapter is registered for {account.provider}.",
            )

        try:
            snapshot = await asyncio.wait_for(
                provider.fetch(account), timeout=self._timeouts.get(account.provider, 15.0)
            )
        except TimeoutError:
            return self._failure_snapshot(
                account, cached, now, ErrorCode.TIMEOUT, "The provider request timed out."
            )
        except Exception as exc:
            return self._failure_snapshot(
                account,
                cached,
                now,
                ErrorCode.NOT_AUTHENTICATED,
                f"The provider could not be queried: {exc}",
            )

        self.cache.put(snapshot)
        return snapshot

    def _is_fresh(self, snapshot: UsageSnapshot | None, provider: str, now: datetime) -> bool:
        if snapshot is None or snapshot.status is not AccountStatus.LIVE:
            return False
        return now - snapshot.retrieved_at <= self._ttls.get(provider, timedelta(0))

    def _failure_snapshot(
        self,
        account: AccountConfig,
        cached: UsageSnapshot | None,
        now: datetime,
        error_code: ErrorCode,
        message: str,
    ) -> UsageSnapshot:
        if cached is not None:
            age = max(now - cached.retrieved_at, timedelta(0))
            fallback_status = AccountStatus.CACHED if age <= FALLBACK_GRACE else AccountStatus.STALE
            return cached.model_copy(
                update={
                    "status": fallback_status,
                    "retrieved_at": now,
                    "message": message,
                    "error_code": error_code,
                }
            )

        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            status=AccountStatus.UNAVAILABLE,
            source="usage_service",
            retrieved_at=now,
            message=message,
            error_code=error_code,
        )
