import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from time_to_sleep.domain import (
    AccountAnalytics,
    AccountConfig,
    AccountStatus,
    AccountStatusView,
    AnalyticsResponse,
    ErrorCode,
    LoginAttempt,
    LoginChallenge,
    Settings,
    UsageSnapshot,
)
from time_to_sleep.providers.base import UsageProvider
from time_to_sleep.providers.codex import CodexLoginSession, LoginTransportFactory

DEFAULT_TTLS = {
    "codex": timedelta(seconds=60),
    "claude": timedelta(minutes=5),
    "antigravity": timedelta(0),
}
DEFAULT_TIMEOUTS = {
    "codex": 15.0,
    "claude": 15.0,
    "antigravity": 15.0,
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

    async def account_statuses(self) -> list[AccountStatusView]:
        return [await self.account_status(account.id) for account in self.settings.accounts]

    async def account_status(self, account_id: str) -> AccountStatusView:
        account = next((item for item in self.settings.accounts if item.id == account_id), None)
        if account is None:
            raise KeyError(account_id)
        cached = self.cache.get(account.id)
        ready = Path(account.expanded_home).exists()
        if cached is not None:
            ready = cached.status is not AccountStatus.UNAVAILABLE
        return AccountStatusView(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            configured_home=account.home,
            ready=ready,
            observed_email=cached.observed_email if cached is not None else None,
            message=cached.message if cached is not None else None,
        )

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


class _LoginRecord:
    def __init__(
        self, attempt: LoginAttempt, session: CodexLoginSession, login_id: str | None
    ) -> None:
        self.attempt = attempt
        self.session = session
        self.login_id = login_id
        self.task: asyncio.Task[None] | None = None


class LoginService:
    def __init__(
        self,
        settings: Settings,
        *,
        command: str = "codex",
        transport_factory: LoginTransportFactory | None = None,
        now: Callable[[], datetime] | None = None,
        attempt_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self.settings = settings
        self.command = command
        self.transport_factory = transport_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._attempt_ttl = attempt_ttl
        self._records: dict[tuple[str, str], _LoginRecord] = {}

    async def start(self, account_id: str, method: str) -> LoginChallenge:
        account = self._account(account_id)
        if account.provider != "codex":
            raise ValueError("Login setup is only supported for Codex accounts")
        if method not in {"browser", "device_code"}:
            raise ValueError(f"Unsupported login method: {method}")

        home = Path(account.expanded_home)
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o700)
        session = CodexLoginSession(
            command=self.command,
            transport_factory=self.transport_factory,
        )
        prompt = await session.start(account, method)
        attempt_id = uuid4().hex
        started_at = self._now()
        expires_at = started_at + self._attempt_ttl
        typed_method = method
        record = _LoginRecord(
            LoginAttempt(
                attempt_id=attempt_id,
                account_id=account.id,
                method=typed_method,
                status="pending",
                started_at=started_at,
                expires_at=expires_at,
            ),
            session,
            prompt.login_id,
        )
        self._records[(account.id, attempt_id)] = record
        record.task = asyncio.create_task(self._monitor(record, account))
        return LoginChallenge(
            attempt_id=attempt_id,
            method=typed_method,
            status="pending",
            auth_url=prompt.auth_url,
            verification_url=prompt.verification_url,
            user_code=prompt.user_code,
        )

    async def status(self, account_id: str, attempt_id: str) -> LoginAttempt:
        record = self._record(account_id, attempt_id)
        if record.attempt.status == "pending" and self._now() >= record.attempt.expires_at:
            await self._expire(record)
        return record.attempt

    async def cancel(self, account_id: str, attempt_id: str) -> LoginAttempt:
        record = self._record(account_id, attempt_id)
        if record.attempt.status == "pending":
            record.attempt = record.attempt.model_copy(
                update={"status": "cancelled", "message": "Login cancelled."}
            )
            with suppress(Exception):
                await record.session.cancel()
            await self._stop(record)
        return record.attempt

    def _account(self, account_id: str) -> AccountConfig:
        for account in self.settings.accounts:
            if account.id == account_id:
                return account
        raise KeyError(account_id)

    def _record(self, account_id: str, attempt_id: str) -> _LoginRecord:
        try:
            return self._records[(account_id, attempt_id)]
        except KeyError as error:
            raise KeyError(attempt_id) from error

    async def _monitor(self, record: _LoginRecord, account: AccountConfig) -> None:
        try:
            timeout = max((record.attempt.expires_at - self._now()).total_seconds(), 0.0)
            completion = await asyncio.wait_for(
                record.session.wait_for_completion(), timeout=timeout
            )
            if not completion.success:
                record.attempt = record.attempt.model_copy(
                    update={
                        "status": "failed",
                        "message": completion.error or "Codex login was not completed.",
                    }
                )
                return
            observed_email = await record.session.account_email()
            if observed_email == account.email:
                record.attempt = record.attempt.model_copy(
                    update={
                        "status": "succeeded",
                        "observed_email": observed_email,
                        "message": "Codex login completed.",
                    }
                )
            else:
                record.attempt = record.attempt.model_copy(
                    update={
                        "status": "failed",
                        "observed_email": observed_email,
                        "message": (
                            f"Codex completed for {observed_email or 'an unknown account'}; "
                            f"expected {account.email}."
                        ),
                    }
                )
        except TimeoutError:
            await self._expire(record)
        except asyncio.CancelledError:
            raise
        except Exception:
            record.attempt = record.attempt.model_copy(
                update={"status": "failed", "message": "Codex login failed."}
            )
        finally:
            await record.session.close()

    async def _expire(self, record: _LoginRecord) -> None:
        if record.attempt.status == "pending":
            record.attempt = record.attempt.model_copy(
                update={"status": "expired", "message": "Login attempt expired."}
            )
        await self._stop(record)

    async def _stop(self, record: _LoginRecord) -> None:
        task = record.task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await record.session.close()


class AnalyticsService:
    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._history: dict[str, list[tuple[datetime, float]]] = {}
        self._now = now or (lambda: datetime.now(UTC))

    def record_snapshot(self, snapshot: UsageSnapshot) -> None:
        if not snapshot.windows:
            return
        max_pct = max(w.used_percent for w in snapshot.windows)
        ts = snapshot.retrieved_at or self._now()
        if snapshot.account_id not in self._history:
            self._history[snapshot.account_id] = []

        hist = self._history[snapshot.account_id]
        if hist and abs((ts - hist[-1][0]).total_seconds()) < 10:
            hist[-1] = (ts, max_pct)
        else:
            hist.append((ts, max_pct))
            if len(hist) > 60:
                hist.pop(0)

    def analyze(
        self, snapshots: list[UsageSnapshot], settings: Settings | None = None
    ) -> AnalyticsResponse:
        for s in snapshots:
            self.record_snapshot(s)

        now = self._now()
        account_analytics: list[AccountAnalytics] = []
        thresholds_map: dict[str, float] = {}
        if settings:
            for acc in settings.accounts:
                thresholds_map[acc.id] = acc.warning_threshold

        for s in snapshots:
            current_pct = max((w.used_percent for w in s.windows), default=0.0)
            hist = self._history.get(s.account_id, [])
            burn_rate: float | None = None
            minutes_to_exhaust: int | None = None

            if len(hist) >= 2:
                first_ts, first_pct = hist[0]
                last_ts, last_pct = hist[-1]
                delta_sec = (last_ts - first_ts).total_seconds()
                if delta_sec >= 60:
                    delta_hours = delta_sec / 3600.0
                    delta_pct = last_pct - first_pct
                    rate = delta_pct / delta_hours
                    if rate > 0.1:
                        burn_rate = round(rate, 2)
                        remaining_pct = 100.0 - current_pct
                        if remaining_pct > 0:
                            minutes_to_exhaust = max(
                                1, int(round((remaining_pct / burn_rate) * 60))
                            )

            account_analytics.append(
                AccountAnalytics(
                    account_id=s.account_id,
                    provider=s.provider,
                    current_percent=current_pct,
                    burn_rate_per_hour=burn_rate,
                    minutes_to_exhaustion=minutes_to_exhaust,
                    status=s.status,
                )
            )

        healthy_alternatives = [
            a
            for a in account_analytics
            if a.status == AccountStatus.LIVE and a.current_percent < 50.0
        ]
        high_usage_accounts = [
            a
            for a in account_analytics
            if a.status == AccountStatus.LIVE
            and a.current_percent >= thresholds_map.get(a.account_id, 80.0)
        ]

        suggestions: list[str] = []
        if high_usage_accounts:
            for high_acc in high_usage_accounts:
                prov_name = high_acc.provider.capitalize()
                if healthy_alternatives:
                    alt_names = ", ".join(
                        f"{a.provider.capitalize()} ({a.account_id})" for a in healthy_alternatives
                    )
                    suggestions.append(
                        f"{prov_name} ({high_acc.account_id}) is at "
                        f"{high_acc.current_percent:.1f}%. "
                        f"Recommended alternatives: {alt_names}."
                    )
                else:
                    suggestions.append(
                        f"{prov_name} ({high_acc.account_id}) is near limit "
                        f"({high_acc.current_percent:.1f}%)."
                    )

        for s in snapshots:
            if s.status == AccountStatus.RATE_LIMITED:
                suggestions.append(
                    f"{s.provider.capitalize()} ({s.account_id}) is currently rate-limited."
                )

        recommended_id = None
        if healthy_alternatives:
            recommended_id = min(healthy_alternatives, key=lambda a: a.current_percent).account_id

        final_accounts = []
        for a in account_analytics:
            is_rec = a.account_id == recommended_id
            reason = "Lowest active usage" if is_rec else None
            final_accounts.append(
                a.model_copy(update={"recommended": is_rec, "recommendation_reason": reason})
            )

        return AnalyticsResponse(
            generated_at=now,
            accounts=final_accounts,
            suggestions=suggestions,
        )
