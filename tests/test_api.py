from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from time_to_sleep.api import app, get_login_service, get_settings, get_usage_service
from time_to_sleep.domain import (
    AccountConfig,
    AccountStatus,
    AccountStatusView,
    LoginAttempt,
    LoginChallenge,
    ProviderName,
    Settings,
    UsageSnapshot,
    UsageWindow,
)


def account(account_id: str, provider: ProviderName) -> AccountConfig:
    return AccountConfig(
        id=account_id,
        provider=provider,
        email=f"{account_id}@example.com",
        home=f"/tmp/{account_id}",
    )


def usage_snapshot(config: AccountConfig) -> UsageSnapshot:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    return UsageSnapshot(
        account_id=config.id,
        provider=config.provider,
        configured_email=config.email,
        observed_email=config.email,
        status=AccountStatus.LIVE,
        source="test",
        observed_at=now,
        retrieved_at=now,
        windows=[UsageWindow(id="primary", used_percent=20, window_minutes=300)],
    )


class FakeUsageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.force_refresh_values: list[bool] = []

    async def collect(self, *, force_refresh: bool = False) -> list[UsageSnapshot]:
        self.force_refresh_values.append(force_refresh)
        return [usage_snapshot(account_config) for account_config in self.settings.accounts]

    async def account_statuses(self) -> list[AccountStatusView]:
        return [
            AccountStatusView(
                account_id=account_config.id,
                provider=account_config.provider,
                configured_email=account_config.email,
                configured_home=account_config.home,
                ready=True,
            )
            for account_config in self.settings.accounts
        ]


class FakeLoginService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.attempt = LoginAttempt(
            attempt_id="attempt-1",
            account_id=settings.accounts[0].id,
            method="browser",
            status="pending",
            started_at=datetime(2026, 8, 18, tzinfo=UTC),
            expires_at=datetime(2026, 8, 18, 0, 10, tzinfo=UTC),
        )

    async def start(self, account_id: str, method: str) -> LoginChallenge:
        account_config = next(
            (item for item in self.settings.accounts if item.id == account_id), None
        )
        if account_config is None:
            raise KeyError(account_id)
        if account_config.provider != "codex":
            raise ValueError("Login setup is only supported for Codex accounts")
        if method not in {"browser", "device_code"}:
            raise ValueError("Unsupported login method")
        return LoginChallenge(
            attempt_id=self.attempt.attempt_id,
            method=method,
            status="pending",
            auth_url="https://auth.example.test/start",
        )

    async def status(self, account_id: str, attempt_id: str) -> LoginAttempt:
        if account_id != self.attempt.account_id or attempt_id != self.attempt.attempt_id:
            raise KeyError(attempt_id)
        return self.attempt

    async def cancel(self, account_id: str, attempt_id: str) -> LoginAttempt:
        if account_id != self.attempt.account_id or attempt_id != self.attempt.attempt_id:
            raise KeyError(attempt_id)
        self.attempt = self.attempt.model_copy(update={"status": "cancelled"})
        return self.attempt


@pytest.fixture
def configured_client() -> Iterator[tuple[TestClient, FakeUsageService, FakeLoginService]]:
    settings = Settings(
        accounts=[
            account("codex-primary", "codex"),
            account("codex-secondary", "codex"),
            account("claude", "claude"),
            account("antigravity", "antigravity"),
        ]
    )
    usage_service = FakeUsageService(settings)
    login_service = FakeLoginService(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_usage_service] = lambda: usage_service
    app.dependency_overrides[get_login_service] = lambda: login_service
    with TestClient(app) as client:
        yield client, usage_service, login_service
    app.dependency_overrides.clear()


def test_health_returns_configured_account_count(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, _, _ = configured_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "configured_accounts": 4}


def test_usage_returns_all_account_records_and_passes_force_refresh(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, usage_service, _ = configured_client

    response = client.get("/v1/usage?force_refresh=true")

    assert response.status_code == 200
    assert len(response.json()["accounts"]) == 4
    assert {item["status"] for item in response.json()["accounts"]} == {"live"}
    assert usage_service.force_refresh_values == [True]


def test_accounts_returns_status_views(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, _, _ = configured_client

    response = client.get("/v1/accounts")

    assert response.status_code == 200
    assert [item["account_id"] for item in response.json()] == [
        "codex-primary",
        "codex-secondary",
        "claude",
        "antigravity",
    ]


def test_login_start_status_and_cancel(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, _, _ = configured_client

    started = client.post("/v1/accounts/codex-primary/login/start", json={"method": "browser"})
    assert started.status_code == 202
    assert started.json()["auth_url"] == "https://auth.example.test/start"
    assert "token" not in started.text.lower()

    attempt_id = started.json()["attempt_id"]
    status = client.get(f"/v1/accounts/codex-primary/login/{attempt_id}")
    cancelled = client.post(f"/v1/accounts/codex-primary/login/{attempt_id}/cancel")

    assert status.status_code == 200
    assert status.json()["status"] == "pending"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_login_rejects_invalid_method_and_unsupported_provider(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, _, _ = configured_client

    invalid = client.post("/v1/accounts/codex-primary/login/start", json={"method": "magic"})
    unsupported = client.post("/v1/accounts/claude/login/start", json={"method": "browser"})

    assert invalid.status_code == 422
    assert unsupported.status_code == 409


def test_unknown_account_and_attempt_return_not_found(
    configured_client: tuple[TestClient, FakeUsageService, FakeLoginService],
) -> None:
    client, _, _ = configured_client

    unknown_account = client.post("/v1/accounts/missing/login/start", json={"method": "browser"})
    unknown_attempt = client.get("/v1/accounts/codex-primary/login/missing")

    assert unknown_account.status_code == 404
    assert unknown_attempt.status_code == 404
