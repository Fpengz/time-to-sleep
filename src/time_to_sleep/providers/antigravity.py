from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode, UsageSnapshot
from time_to_sleep.providers.parsers import parse_antigravity_log


class AntigravityProvider:
    def __init__(
        self,
        now: Callable[[], datetime] | None = None,
        max_bytes: int = 512 * 1024,
    ) -> None:
        self.now = now or (lambda: datetime.now(UTC))
        self.max_bytes = max_bytes

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        retrieved_at = self.now().astimezone(UTC)
        log_path = Path(account.expanded_home) / "logs" / "language_server.log"
        try:
            with log_path.open("rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - self.max_bytes))
                content = handle.read().decode("utf-8", errors="replace")
            parsed = parse_antigravity_log(content, now=retrieved_at)
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=account.email,
                status=AccountStatus.LIVE,
                source="antigravity_log",
                observed_at=parsed.observed_at,
                retrieved_at=retrieved_at,
                windows=parsed.windows,
            )
        except FileNotFoundError:
            return self._unavailable(
                account, retrieved_at, ErrorCode.NOT_CONFIGURED, f"Agy log not found: {log_path}"
            )
        except ValueError as error:
            return self._unavailable(account, retrieved_at, ErrorCode.NO_RECENT_DATA, str(error))

    @staticmethod
    def _unavailable(
        account: AccountConfig,
        retrieved_at: datetime,
        error_code: ErrorCode,
        message: str,
    ) -> UsageSnapshot:
        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            observed_email=account.email,
            status=AccountStatus.UNAVAILABLE,
            source="antigravity_log",
            retrieved_at=retrieved_at,
            message=message,
            error_code=error_code,
        )
