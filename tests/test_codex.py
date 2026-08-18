from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode
from time_to_sleep.providers.codex import CodexProvider


class FakeTransport:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.notifications: list[str] = []
        self.closed = False

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        return self.responses[method]

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        del params
        self.notifications.append(method)

    async def close(self) -> None:
        self.closed = True


def account(home: str = "~/.codex") -> AccountConfig:
    return AccountConfig(id="codex", provider="codex", email="wzf5350@gmail.com", home=home)


@pytest.mark.asyncio
async def test_codex_adapter_reads_identity_and_rate_limits(tmp_path: Path) -> None:
    transport = FakeTransport(
        {
            "initialize": {"id": 1, "result": {}},
            "account/read": {
                "id": 2,
                "result": {
                    "account": {"type": "chatgpt", "email": "wzf5350@gmail.com", "planType": "team"}
                },
            },
            "account/rateLimits/read": {
                "id": 3,
                "result": {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 15,
                            "windowDurationMins": 10080,
                            "resetsAt": 1787460588,
                        },
                        "secondary": None,
                    }
                },
            },
        }
    )

    async def factory(_: AccountConfig) -> FakeTransport:
        return transport

    snapshot = await CodexProvider(transport_factory=factory).fetch(account(str(tmp_path)))

    assert snapshot.observed_email == "wzf5350@gmail.com"
    assert snapshot.status is AccountStatus.LIVE
    assert snapshot.plan_type == "team"
    assert snapshot.windows[0].used_percent == 15
    assert snapshot.windows[0].window_minutes == 10080
    assert "initialized" in transport.notifications
    assert transport.closed


@pytest.mark.asyncio
async def test_codex_adapter_marks_identity_mismatch_without_returning_live_data(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        {
            "initialize": {"id": 1, "result": {}},
            "account/read": {
                "id": 2,
                "result": {"account": {"email": "wrong@example.com"}},
            },
            "account/rateLimits/read": {"id": 3, "result": {"rateLimits": {}}},
        }
    )

    async def factory(_: AccountConfig) -> FakeTransport:
        return transport

    snapshot = await CodexProvider(transport_factory=factory).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.UNAVAILABLE
    assert snapshot.error_code is ErrorCode.IDENTITY_MISMATCH
    assert snapshot.windows == []


@pytest.mark.asyncio
async def test_codex_adapter_uses_rollout_snapshot_when_live_transport_fails(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions" / "2026" / "08" / "18"
    sessions.mkdir(parents=True)
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    (sessions / "rollout.jsonl").write_text(
        f'{{"timestamp":"{observed_at}","payload":{{"rate_limits":{{'
        '"primary":{"used_percent":22,"window_minutes":300,"resets_at":1780000000}'
        "}}}\n",
        encoding="utf-8",
    )

    async def factory(_: AccountConfig) -> FakeTransport:
        raise TimeoutError("provider timed out")

    snapshot = await CodexProvider(transport_factory=factory).fetch(account(str(tmp_path)))

    assert snapshot.status is AccountStatus.CACHED
    assert snapshot.error_code is ErrorCode.TIMEOUT
    assert snapshot.windows[0].used_percent == 22
