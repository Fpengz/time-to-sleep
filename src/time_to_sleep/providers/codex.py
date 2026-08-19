import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from time_to_sleep import __version__
from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode, UsageSnapshot, UsageWindow
from time_to_sleep.providers.base import JsonRpcTransport, ParsedWindows
from time_to_sleep.providers.parsers import parse_codex_rollout

TransportFactory = Callable[[AccountConfig], Awaitable[JsonRpcTransport]]
LoginTransportFactory = Callable[[AccountConfig], Awaitable["CodexLoginTransport"]]
_FALLBACK_MAX_AGE = timedelta(minutes=15)


class CodexLoginTransport(Protocol):
    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...

    async def next_message(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class CodexLoginChallenge:
    auth_url: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    login_id: str | None = None


@dataclass(frozen=True)
class CodexLoginCompletion:
    login_id: str | None
    success: bool
    error: str | None = None


class CodexRpcError(RuntimeError):
    pass


class SubprocessJsonRpcTransport:
    def __init__(self, process: asyncio.subprocess.Process, timeout: float = 10.0) -> None:
        self.process = process
        self.timeout = timeout
        self._next_id = 1

    @classmethod
    async def open(
        cls, account: AccountConfig, command: str = "codex"
    ) -> "SubprocessJsonRpcTransport":
        if shutil.which(command) is None:
            raise FileNotFoundError(f"Codex executable not found: {command}")
        home = Path(account.expanded_home)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(home)
        process = await asyncio.create_subprocess_exec(
            command,
            "app-server",
            "--stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
        )
        return cls(process)

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._write({"method": method, "id": request_id, "params": params or {}})
        while True:
            message = await self._read(timeout=self.timeout)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CodexRpcError(str(message["error"]))
            return message

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"method": method, "params": params or {}})

    async def _write(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise CodexRpcError("Codex app-server stdin is unavailable")
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self, *, timeout: float | None) -> dict[str, Any]:
        if self.process.stdout is None:
            raise CodexRpcError("Codex app-server stdout is unavailable")
        read = self.process.stdout.readline()
        raw = await read if timeout is None else await asyncio.wait_for(read, timeout=timeout)
        if not raw:
            raise CodexRpcError("Codex app-server exited before responding")
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as error:
            raise CodexRpcError("Codex app-server returned invalid JSON") from error
        if not isinstance(message, dict):
            raise CodexRpcError("Codex app-server returned a non-object message")
        return message

    async def next_message(self) -> dict[str, Any]:
        return await self._read(timeout=None)

    async def close(self) -> None:
        if self.process.returncode is not None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=1)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()


class CodexProvider:
    def __init__(
        self,
        command: str = "codex",
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self.command = command
        self.transport_factory = transport_factory

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        retrieved_at = datetime.now(UTC)
        home = Path(account.expanded_home)
        if not home.exists():
            return self._unavailable(
                account,
                retrieved_at,
                ErrorCode.NOT_CONFIGURED,
                f"Codex home does not exist: {account.home}",
            )

        transport: JsonRpcTransport | None = None
        try:
            transport = await self._open_transport(account)
            await transport.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "time_to_sleep",
                        "title": "Time-to-Sleep",
                        "version": __version__,
                    }
                },
            )
            await transport.notify("initialized")
            account_response = await transport.request("account/read", {"refreshToken": False})
            account_result = account_response.get("result")
            account_data = (
                account_result.get("account") if isinstance(account_result, dict) else None
            )
            if not isinstance(account_data, dict):
                return self._unavailable(
                    account,
                    retrieved_at,
                    ErrorCode.NOT_AUTHENTICATED,
                    "Codex did not return an authenticated account",
                )
            observed_email = _optional_text(account_data.get("email"))
            if observed_email != account.email:
                return self._unavailable(
                    account,
                    retrieved_at,
                    ErrorCode.IDENTITY_MISMATCH,
                    f"Codex reported {observed_email or 'no email'}, expected {account.email}",
                    observed_email=observed_email,
                )

            limits_response = await transport.request("account/rateLimits/read")
            result = limits_response.get("result", {})
            limits = result.get("rateLimits") or {}
            windows = self._parse_rate_limits(limits)
            if not windows:
                raise CodexRpcError("Codex returned no rate limit windows")
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=observed_email,
                status=AccountStatus.LIVE,
                source="codex_app_server",
                observed_at=retrieved_at,
                retrieved_at=retrieved_at,
                windows=windows,
                plan_type=limits.get("planType") or account_data.get("planType"),
            )
        except FileNotFoundError as error:
            return self._with_fallback(
                account, retrieved_at, ErrorCode.NOT_CONFIGURED, str(error), home
            )
        except TimeoutError:
            return self._with_fallback(
                account, retrieved_at, ErrorCode.TIMEOUT, "Codex app-server timed out", home
            )
        except CodexRpcError as error:
            return self._with_fallback(
                account, retrieved_at, ErrorCode.NOT_AUTHENTICATED, str(error), home
            )
        finally:
            if transport is not None:
                await transport.close()

    async def _open_transport(self, account: AccountConfig) -> JsonRpcTransport:
        if self.transport_factory is not None:
            return await self.transport_factory(account)
        return await SubprocessJsonRpcTransport.open(account, self.command)

    @staticmethod
    def _parse_rate_limits(raw: dict[str, Any]) -> list[UsageWindow]:
        windows: list[UsageWindow] = []
        for window_id in ("primary", "secondary"):
            window = raw.get(window_id)
            if not isinstance(window, dict):
                continue
            used = window.get("usedPercent")
            duration = window.get("windowDurationMins")
            reset = window.get("resetsAt")
            if not isinstance(used, (int, float)):
                continue
            windows.append(
                UsageWindow(
                    id=window_id,
                    used_percent=float(used),
                    window_minutes=int(duration) if duration is not None else None,
                    resets_at=(
                        datetime.fromtimestamp(float(reset), tz=UTC) if reset is not None else None
                    ),
                )
            )
        return windows

    def _with_fallback(
        self,
        account: AccountConfig,
        retrieved_at: datetime,
        error_code: ErrorCode,
        message: str,
        home: Path,
    ) -> UsageSnapshot:
        try:
            parsed = self._read_rollout_fallback(home)
        except (OSError, ValueError):
            return self._unavailable(account, retrieved_at, error_code, message)
        status = (
            AccountStatus.CACHED
            if retrieved_at - parsed.observed_at <= _FALLBACK_MAX_AGE
            else AccountStatus.STALE
        )
        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            status=status,
            source="codex_rollout",
            observed_at=parsed.observed_at,
            retrieved_at=retrieved_at,
            windows=parsed.windows,
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def _read_rollout_fallback(home: Path) -> ParsedWindows:
        files = sorted(
            [*home.glob("sessions/**/*.jsonl"), *home.glob("archived_sessions/**/*.jsonl")],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:40]
        newest: ParsedWindows | None = None
        for path in files:
            content = path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_codex_rollout(content.splitlines())
            if newest is None or parsed.observed_at > newest.observed_at:
                newest = parsed
        if newest is None:
            raise ValueError("no Codex rollout snapshot found")
        return newest

    @staticmethod
    def _unavailable(
        account: AccountConfig,
        retrieved_at: datetime,
        error_code: ErrorCode,
        message: str,
        observed_email: str | None = None,
    ) -> UsageSnapshot:
        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            observed_email=observed_email,
            status=AccountStatus.UNAVAILABLE,
            source="codex_app_server",
            retrieved_at=retrieved_at,
            message=message,
            error_code=error_code,
        )


class CodexLoginSession:
    def __init__(
        self,
        command: str = "codex",
        transport_factory: LoginTransportFactory | None = None,
    ) -> None:
        self.command = command
        self.transport_factory = transport_factory
        self.transport: CodexLoginTransport | None = None
        self.login_id: str | None = None

    async def start(self, account: AccountConfig, method: str) -> CodexLoginChallenge:
        if method not in {"browser", "device_code"}:
            raise ValueError(f"Unsupported Codex login method: {method}")
        self.transport = await self._open_transport(account)
        try:
            await self.transport.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "time_to_sleep",
                        "title": "Time-to-Sleep",
                        "version": __version__,
                    }
                },
            )
            await self.transport.notify("initialized")
            response = await self.transport.request(
                "account/login/start",
                {"type": "chatgpt" if method == "browser" else "chatgptDeviceCode"},
            )
            result = response.get("result", {})
            if not isinstance(result, dict):
                raise CodexRpcError("Codex returned an invalid login challenge")
            self.login_id = _optional_text(result.get("loginId"))
            return CodexLoginChallenge(
                auth_url=_optional_text(result.get("authUrl")),
                verification_url=_optional_text(result.get("verificationUrl")),
                user_code=_optional_text(result.get("userCode")),
                login_id=self.login_id,
            )
        except Exception:
            await self.close()
            raise

    async def wait_for_completion(self) -> CodexLoginCompletion:
        if self.transport is None:
            raise CodexRpcError("Codex login session has not started")
        while True:
            message = await self.transport.next_message()
            if message.get("method") == "account/login/completed":
                params = message.get("params")
                if not isinstance(params, dict):
                    raise CodexRpcError("Codex returned an invalid login completion")
                message_login_id = _optional_text(params.get("loginId"))
                if self.login_id is not None and message_login_id not in {
                    None,
                    self.login_id,
                }:
                    continue
                return CodexLoginCompletion(
                    login_id=message_login_id,
                    success=params.get("success") is True,
                    error=_optional_text(params.get("error")),
                )

    async def cancel(self) -> None:
        if self.transport is None or self.login_id is None:
            return
        await self.transport.request("account/login/cancel", {"loginId": self.login_id})

    async def account_email(self) -> str | None:
        if self.transport is None:
            raise CodexRpcError("Codex login session has not started")
        response = await self.transport.request("account/read", {"refreshToken": True})
        account_data = response.get("result", {}).get("account", {})
        if not isinstance(account_data, dict):
            return None
        return _optional_text(account_data.get("email"))

    async def close(self) -> None:
        if self.transport is not None:
            transport = self.transport
            self.transport = None
            await transport.close()

    async def _open_transport(self, account: AccountConfig) -> CodexLoginTransport:
        if self.transport_factory is not None:
            return await self.transport_factory(account)
        return await SubprocessJsonRpcTransport.open(account, self.command)


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
