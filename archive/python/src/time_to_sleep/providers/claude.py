import json
import os
import platform
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from getpass import getuser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode, UsageSnapshot, UsageWindow
from time_to_sleep.providers.parsers import parse_claude_plan_history

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_WEB_USAGE_URL = "https://claude.ai/api/organizations/{organization_id}/usage"
_FALLBACK_MAX_AGE = timedelta(minutes=15)

WebUsageFetcher = Callable[[AccountConfig], Awaitable[Mapping[str, Any] | None]]


class ClaudeCredentialSource:
    def __init__(
        self,
        home: Path,
        keychain_loader: Callable[[], str | None] | None = None,
    ) -> None:
        self.home = home
        self.keychain_loader = keychain_loader
        self._cached_token: str | None = None

    def get_token(self) -> str | None:
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if token:
            return token.strip()

        if self._cached_token is not None:
            return self._cached_token

        raw = self.keychain_loader() if self.keychain_loader is not None else self._read_keychain()
        token = self._extract_token(raw)
        if token:
            self._cached_token = token
            return token

        credentials_path = self.home / ".credentials.json"
        if credentials_path.is_file():
            token = self._extract_token(credentials_path.read_text(encoding="utf-8"))
            if token:
                self._cached_token = token
                return token
        return None

    def invalidate(self) -> None:
        self._cached_token = None

    @staticmethod
    def _extract_token(raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip() or None
        if isinstance(document, Mapping):
            oauth = document.get("claudeAiOauth")
            if isinstance(oauth, Mapping):
                token = oauth.get("accessToken")
                return token.strip() if isinstance(token, str) and token.strip() else None
        return None

    @staticmethod
    def _read_keychain() -> str | None:
        if platform.system() != "Darwin":
            return None
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-a",
                getuser(),
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        return result.stdout if result.returncode == 0 else None


class ClaudeProvider:
    def __init__(
        self,
        credential_source_factory: Callable[[AccountConfig], ClaudeCredentialSource] | None = None,
        include_desktop_history: bool = True,
        web_usage_fetcher: WebUsageFetcher | None = None,
    ) -> None:
        self.credential_source_factory = credential_source_factory
        self.include_desktop_history = include_desktop_history
        self.web_usage_fetcher = web_usage_fetcher or self._fetch_configured_web_usage
        self._rate_limited_until: datetime | None = None

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        retrieved_at = datetime.now(UTC)
        source = (
            self.credential_source_factory(account)
            if self.credential_source_factory is not None
            else ClaudeCredentialSource(Path(account.expanded_home))
        )
        token = source.get_token()
        if not token:
            return self._with_fallback(
                account,
                retrieved_at,
                ErrorCode.NOT_AUTHENTICATED,
                "No Claude OAuth credential is available",
            )

        if self._rate_limited_until is not None and retrieved_at < self._rate_limited_until:
            web_snapshot = await self._fetch_web_snapshot(account, retrieved_at)
            if web_snapshot is not None:
                return web_snapshot
            return self._with_fallback(
                account,
                retrieved_at,
                ErrorCode.RATE_LIMITED,
                self._rate_limit_message(self._rate_limited_until),
            )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    CLAUDE_USAGE_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "anthropic-beta": "oauth-2025-04-20",
                    },
                )
            if response.status_code == 401:
                if hasattr(source, "invalidate"):
                    source.invalidate()
                return self._with_fallback(
                    account,
                    retrieved_at,
                    ErrorCode.AUTHENTICATION_EXPIRED,
                    "Claude OAuth credential is expired; run claude auth login",
                )
            if response.status_code == 429:
                self._rate_limited_until = retrieved_at + self._retry_after(response)
                web_snapshot = await self._fetch_web_snapshot(account, retrieved_at)
                if web_snapshot is not None:
                    return web_snapshot
                return self._with_fallback(
                    account,
                    retrieved_at,
                    ErrorCode.RATE_LIMITED,
                    self._rate_limit_message(self._rate_limited_until),
                )
            response.raise_for_status()
            windows = self._parse_usage(response.json())
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=account.email,
                status=AccountStatus.LIVE,
                source="claude_oauth",
                observed_at=retrieved_at,
                retrieved_at=retrieved_at,
                windows=windows,
            )
        except httpx.TimeoutException:
            return self._with_fallback(
                account, retrieved_at, ErrorCode.TIMEOUT, "Claude usage request timed out"
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            return self._with_fallback(
                account,
                retrieved_at,
                ErrorCode.PARSE_ERROR,
                f"Claude usage request failed: {error}",
            )

    async def _fetch_web_snapshot(
        self, account: AccountConfig, retrieved_at: datetime
    ) -> UsageSnapshot | None:
        try:
            document = await self.web_usage_fetcher(account)
            if document is None:
                return None
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=account.email,
                status=AccountStatus.LIVE,
                source="claude_web",
                observed_at=retrieved_at,
                retrieved_at=retrieved_at,
                windows=self._parse_usage(document),
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return None

    @staticmethod
    async def _fetch_configured_web_usage(account: AccountConfig) -> Mapping[str, Any] | None:
        del account
        session_cookie = os.environ.get("CLAUDE_WEB_COOKIE") or os.environ.get(
            "CLAUDE_WEB_SESSION_KEY"
        )
        organization_id = os.environ.get("CLAUDE_WEB_ORGANIZATION_ID") or os.environ.get(
            "CLAUDE_ORGANIZATION_ID"
        )
        if not session_cookie or not organization_id:
            return None
        url = CLAUDE_WEB_USAGE_URL.format(organization_id=quote(organization_id, safe=""))
        cookie = session_cookie if "=" in session_cookie else f"sessionKey={session_cookie}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Cookie": cookie,
                    "Origin": "https://claude.ai",
                    "Referer": "https://claude.ai/",
                    "User-Agent": "time-to-sleep/1.0",
                },
            )
        if response.status_code in {401, 403, 404, 429}:
            return None
        response.raise_for_status()
        document = response.json()
        return document if isinstance(document, Mapping) else None

    @staticmethod
    def _retry_after(response: httpx.Response) -> timedelta:
        value = response.headers.get("Retry-After")
        try:
            seconds = max(1, int(value)) if value is not None else 300
        except ValueError:
            seconds = 300
        return timedelta(seconds=seconds)

    @staticmethod
    def _rate_limit_message(retry_at: datetime) -> str:
        minutes = max(1, int((retry_at - datetime.now(UTC)).total_seconds() // 60))
        return f"Claude usage endpoint is rate limited; retry after about {minutes} minutes"

    @staticmethod
    def _parse_usage(document: Any) -> list[UsageWindow]:
        if not isinstance(document, Mapping):
            raise ValueError("Claude usage response is not an object")
        windows: list[UsageWindow] = []
        for window_id, duration in (("five_hour", 300), ("seven_day", 10080)):
            raw = document.get(window_id)
            if not isinstance(raw, Mapping):
                continue
            used = raw.get("utilization", raw.get("used_percentage"))
            if not isinstance(used, (int, float)):
                continue
            reset = raw.get("resets_at")
            windows.append(
                UsageWindow(
                    id=window_id,
                    used_percent=float(used),
                    window_minutes=duration,
                    resets_at=ClaudeProvider._parse_reset(reset),
                )
            )
        if not windows:
            raise ValueError("Claude usage response has no usage windows")
        return windows

    @staticmethod
    def _parse_reset(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            return aware.astimezone(UTC)
        raise ValueError("Claude reset timestamp is invalid")

    def _with_fallback(
        self,
        account: AccountConfig,
        retrieved_at: datetime,
        error_code: ErrorCode,
        message: str,
    ) -> UsageSnapshot:
        try:
            parsed = self._read_plan_history(account, include_desktop=self.include_desktop_history)
        except (OSError, ValueError):
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=account.email,
                status=(
                    AccountStatus.RATE_LIMITED
                    if error_code is ErrorCode.RATE_LIMITED
                    else AccountStatus.UNAVAILABLE
                ),
                source="claude_oauth",
                retrieved_at=retrieved_at,
                message=message,
                error_code=error_code,
            )
        status = (
            AccountStatus.CACHED
            if retrieved_at - parsed.observed_at <= _FALLBACK_MAX_AGE
            else AccountStatus.STALE
        )
        if status is AccountStatus.STALE:
            stale_status = (
                AccountStatus.RATE_LIMITED
                if error_code is ErrorCode.RATE_LIMITED
                else AccountStatus.UNAVAILABLE
            )
            stale_error = (
                error_code if error_code is ErrorCode.RATE_LIMITED else ErrorCode.NO_RECENT_DATA
            )
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=account.email,
                status=stale_status,
                source="claude_plan_history",
                observed_at=parsed.observed_at,
                retrieved_at=retrieved_at,
                message=(
                    f"{message}; latest local sample is stale ({parsed.observed_at.isoformat()})"
                ),
                error_code=stale_error,
            )
        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            observed_email=account.email,
            status=status,
            source="claude_plan_history",
            observed_at=parsed.observed_at,
            retrieved_at=retrieved_at,
            windows=parsed.windows,
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def _read_plan_history(account: AccountConfig, *, include_desktop: bool):
        paths = [Path(account.expanded_home) / "plan-usage-history.json"]
        if include_desktop and platform.system() == "Darwin":
            paths.append(Path.home() / "Library/Application Support/Claude/plan-usage-history.json")
        for path in paths:
            if path.is_file():
                document = json.loads(path.read_text(encoding="utf-8"))
                return parse_claude_plan_history(document)
        raise FileNotFoundError("Claude plan usage history was not found")
