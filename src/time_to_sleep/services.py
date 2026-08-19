import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from time_to_sleep.domain import (
    AccountConfig,
    AccountStatus,
    AccountStatusView,
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
