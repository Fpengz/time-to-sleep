import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
from time_to_sleep.services import LoginService, ProviderRegistry, UsageCache, UsageService


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


class FakeLoginTransport:
    def __init__(self, observed_email: str) -> None:
        self.observed_email = observed_email
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.login_types: list[str] = []
        self.closed = False

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "account/login/start":
            assert params is not None
            self.login_types.append(params["type"])
            return {
                "result": {
                    "authUrl": "https://auth.example.test/start",
                    "verificationUrl": "https://auth.example.test/verify",
                    "userCode": "ABCD-EFGH",
                }
            }
        if method == "account/read":
            return {"result": {"account": {"email": self.observed_email}}}
        return {"result": {}}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        del method, params

    async def next_message(self) -> dict[str, Any]:
        return await self.events.get()

    async def close(self) -> None:
        self.closed = True


def login_account(home: Path, provider: ProviderName = "codex") -> AccountConfig:
    return AccountConfig(
        id="login-account",
        provider=provider,
        email="wzf0513@gmail.com",
        home=str(home),
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "expected_type"),
    [("browser", "chatgpt"), ("device_code", "chatgptDeviceCode")],
)
async def test_login_service_starts_isolated_codex_challenge(
    tmp_path: Path, method: str, expected_type: str
) -> None:
    account_config = login_account(tmp_path / "secondary")
    transport = FakeLoginTransport(account_config.email)

    async def factory(_: AccountConfig) -> FakeLoginTransport:
        return transport

    service = LoginService(Settings(accounts=[account_config]), transport_factory=factory)

    challenge = await service.start(account_config.id, method)
    attempt = await service.status(account_config.id, challenge.attempt_id)

    assert challenge.method == method
    assert challenge.status == "pending"
    assert challenge.auth_url == "https://auth.example.test/start"
    assert challenge.user_code == "ABCD-EFGH"
    assert attempt.status == "pending"
    assert transport.login_types == [expected_type]
    assert (tmp_path / "secondary").stat().st_mode & 0o777 == 0o700

    await service.cancel(account_config.id, challenge.attempt_id)


@pytest.mark.asyncio
async def test_login_service_verifies_email_after_completion(tmp_path: Path) -> None:
    account_config = login_account(tmp_path / "secondary")
    transport = FakeLoginTransport(account_config.email)

    async def factory(_: AccountConfig) -> FakeLoginTransport:
        return transport

    service = LoginService(Settings(accounts=[account_config]), transport_factory=factory)
    challenge = await service.start(account_config.id, "browser")
    await transport.events.put({"method": "account/login/completed", "params": {}})
    await asyncio.sleep(0.01)

    attempt = await service.status(account_config.id, challenge.attempt_id)
    assert attempt.status == "succeeded"
    assert attempt.observed_email == account_config.email
    assert transport.closed


@pytest.mark.asyncio
async def test_login_service_rejects_identity_mismatch(tmp_path: Path) -> None:
    account_config = login_account(tmp_path / "secondary")
    transport = FakeLoginTransport("wrong@example.com")

    async def factory(_: AccountConfig) -> FakeLoginTransport:
        return transport

    service = LoginService(Settings(accounts=[account_config]), transport_factory=factory)
    challenge = await service.start(account_config.id, "browser")
    await transport.events.put({"method": "account/login/completed", "params": {}})
    await asyncio.sleep(0.01)

    attempt = await service.status(account_config.id, challenge.attempt_id)
    assert attempt.status == "failed"
    assert attempt.observed_email == "wrong@example.com"
    assert transport.closed


@pytest.mark.asyncio
async def test_login_service_expires_and_closes_pending_attempt(tmp_path: Path) -> None:
    account_config = login_account(tmp_path / "secondary")
    transport = FakeLoginTransport(account_config.email)

    async def factory(_: AccountConfig) -> FakeLoginTransport:
        return transport

    service = LoginService(
        Settings(accounts=[account_config]),
        transport_factory=factory,
        attempt_ttl=timedelta(milliseconds=10),
    )
    challenge = await service.start(account_config.id, "device_code")
    await asyncio.sleep(0.03)

    attempt = await service.status(account_config.id, challenge.attempt_id)
    assert attempt.status == "expired"
    assert transport.closed


@pytest.mark.asyncio
async def test_login_service_rejects_non_codex_accounts(tmp_path: Path) -> None:
    account_config = login_account(tmp_path / "claude", provider="claude")
    service = LoginService(Settings(accounts=[account_config]))

    with pytest.raises(ValueError, match="Codex"):
        await service.start(account_config.id, "browser")
