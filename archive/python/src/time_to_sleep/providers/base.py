from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from time_to_sleep.domain import AccountConfig, UsageSnapshot, UsageWindow


@dataclass(frozen=True)
class ParsedWindows:
    observed_at: datetime
    windows: list[UsageWindow]
    message: str | None = None


class UsageProvider(Protocol):
    async def fetch(self, account: AccountConfig) -> UsageSnapshot: ...


class JsonRpcTransport(Protocol):
    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...

    async def close(self) -> None: ...
