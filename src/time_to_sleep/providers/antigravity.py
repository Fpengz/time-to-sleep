import asyncio
import os
import pty
import re
import shutil
import signal
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from time_to_sleep.domain import AccountConfig, AccountStatus, ErrorCode, UsageSnapshot
from time_to_sleep.providers.parsers import parse_antigravity_quota_summary

AntigravitySource = Callable[
    [AccountConfig], Awaitable[tuple[Mapping[str, Any], Mapping[str, Any] | None, str]]
]


class AntigravitySourceError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class _LocalServer:
    def __init__(self, pid: int, port: int, csrf_token: str | None) -> None:
        self.pid = pid
        self.port = port
        self.csrf_token = csrf_token


class _OwnedCli:
    def __init__(self, process: subprocess.Popen[Any], master_fd: int) -> None:
        self.process = process
        self.master_fd = master_fd


class AntigravityProvider:
    def __init__(
        self,
        now: Callable[[], datetime] | None = None,
        source: AntigravitySource | None = None,
        command: str = "agy",
        startup_timeout: float = 10.0,
        request_timeout: float = 5.0,
    ) -> None:
        self.now = now or (lambda: datetime.now(UTC))
        self.source = source or self._fetch_from_local_server
        self.command = command
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout

    async def fetch(self, account: AccountConfig) -> UsageSnapshot:
        retrieved_at = self.now().astimezone(UTC)
        try:
            quota_document, status_document, source = await self.source(account)
            observed_email, plan_type = self._parse_user_status(status_document)
            if observed_email is not None and observed_email.casefold() != account.email.casefold():
                return self._unavailable(
                    account,
                    retrieved_at,
                    ErrorCode.IDENTITY_MISMATCH,
                    f"Antigravity reported {observed_email}, expected {account.email}",
                    observed_email=observed_email,
                    source=source,
                )
            parsed = parse_antigravity_quota_summary(quota_document, now=retrieved_at)
            return UsageSnapshot(
                account_id=account.id,
                provider=account.provider,
                configured_email=account.email,
                observed_email=observed_email or account.email,
                status=AccountStatus.LIVE,
                source=source,
                observed_at=parsed.observed_at,
                retrieved_at=retrieved_at,
                windows=parsed.windows,
                plan_type=plan_type,
            )
        except AntigravitySourceError as error:
            return self._unavailable(
                account,
                retrieved_at,
                error.error_code,
                error.message,
                source="antigravity_local",
            )
        except (TypeError, ValueError) as error:
            return self._unavailable(
                account,
                retrieved_at,
                ErrorCode.PARSE_ERROR,
                f"Antigravity quota response could not be parsed: {error}",
                source="antigravity_local",
            )

    async def _fetch_from_local_server(
        self, account: AccountConfig
    ) -> tuple[Mapping[str, Any], Mapping[str, Any] | None, str]:
        del account
        server = await self._find_server()
        owned_cli: _OwnedCli | None = None
        try:
            if server is None:
                owned_cli = self._start_cli()
                server = await self._wait_for_server(
                    owned_cli.process.pid, owned_cli.process, owned_cli.master_fd
                )
            if server is None:
                raise AntigravitySourceError(
                    ErrorCode.NOT_AUTHENTICATED,
                    "Antigravity is not authenticated; run agy and sign in first",
                )
            return await self._read_server(server)
        finally:
            if owned_cli is not None:
                await self._stop_cli(owned_cli)

    async def _read_server(
        self, server: _LocalServer
    ) -> tuple[Mapping[str, Any], Mapping[str, Any] | None, str]:
        headers = {"Connect-Protocol-Version": "1"}
        if server.csrf_token:
            headers["X-Codeium-Csrf-Token"] = server.csrf_token
        async with httpx.AsyncClient(verify=False, timeout=self.request_timeout) as client:
            deadline = asyncio.get_running_loop().time() + self.startup_timeout
            quota_document: Mapping[str, Any] | None = None
            status_document: Mapping[str, Any] | None = None
            while asyncio.get_running_loop().time() < deadline:
                quota_document = await self._post_first_available(
                    client, server.port, "RetrieveUserQuotaSummary", headers
                )
                status_document = await self._post_first_available(
                    client, server.port, "GetUserStatus", headers
                )
                if quota_document is not None:
                    break
                await asyncio.sleep(0.25)
        if quota_document is None:
            raise AntigravitySourceError(
                ErrorCode.NO_RECENT_DATA,
                "Antigravity did not return a quota summary; retry while agy is signed in",
            )
        source = "antigravity_cli" if not server.csrf_token else "antigravity_app"
        return quota_document, status_document, source

    async def _post_first_available(
        self,
        client: httpx.AsyncClient,
        port: int,
        method: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, Any] | None:
        for scheme in ("https", "http"):
            try:
                response = await client.post(
                    f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}",
                    headers={**headers, "Content-Type": "application/json"},
                    json={},
                )
                if response.status_code != 200:
                    continue
                document = response.json()
                if isinstance(document, Mapping):
                    return document
            except (httpx.HTTPError, ValueError):
                continue
        return None

    async def _find_server(self, pid: int | None = None) -> _LocalServer | None:
        process_rows = await self._process_rows()
        for process_pid, command_line in process_rows:
            if pid is not None and process_pid != pid:
                continue
            if not self._is_antigravity_process(command_line):
                continue
            csrf_token = self._flag_value(command_line, "csrf_token")
            for port in await self._listening_ports(process_pid):
                server = _LocalServer(process_pid, port, csrf_token)
                if await self._post_probe(server):
                    return server
        return None

    async def _wait_for_server(
        self, pid: int, process: subprocess.Popen[Any], master_fd: int
    ) -> _LocalServer | None:
        deadline = asyncio.get_running_loop().time() + self.startup_timeout
        while asyncio.get_running_loop().time() < deadline:
            self._drain_cli_output(owned_master_fd=master_fd)
            if process.poll() is not None:
                return None
            server = await self._find_server(pid)
            if server is not None:
                return server
            await asyncio.sleep(0.25)
        return None

    async def _post_probe(self, server: _LocalServer) -> bool:
        headers = {"Connect-Protocol-Version": "1"}
        if server.csrf_token:
            headers["X-Codeium-Csrf-Token"] = server.csrf_token
        async with httpx.AsyncClient(verify=False, timeout=1.5) as client:
            return (
                await self._post_first_available(client, server.port, "GetUnleashData", headers)
            ) is not None

    def _start_cli(self) -> _OwnedCli:
        command = self._resolve_command()
        master_fd: int | None = None
        slave_fd: int | None = None
        try:
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                [command],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(Path.cwd()),
                start_new_session=True,
            )
        except OSError as error:
            if master_fd is not None:
                with suppress(OSError):
                    os.close(master_fd)
            if slave_fd is not None:
                with suppress(OSError):
                    os.close(slave_fd)
            raise AntigravitySourceError(
                ErrorCode.NOT_CONFIGURED,
                f"Could not start Antigravity CLI: {error}",
            ) from error
        os.close(slave_fd)
        os.set_blocking(master_fd, False)
        return _OwnedCli(process, master_fd)

    def _resolve_command(self) -> str:
        resolved = shutil.which(self.command)
        if resolved:
            return resolved
        for candidate in (
            Path.home() / ".local" / "bin" / self.command,
            Path("/opt/homebrew/bin") / self.command,
            Path("/usr/local/bin") / self.command,
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        raise AntigravitySourceError(
            ErrorCode.NOT_CONFIGURED,
            f"Antigravity CLI executable was not found: {self.command}",
        )

    async def _stop_cli(self, owned_cli: _OwnedCli) -> None:
        process = owned_cli.process
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.send_signal(signal.SIGINT)
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 1)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await asyncio.to_thread(process.wait)
        with suppress(OSError):
            os.close(owned_cli.master_fd)

    @staticmethod
    def _drain_cli_output(*, owned_master_fd: int) -> None:
        while True:
            try:
                if not os.read(owned_master_fd, 8192):
                    return
            except (BlockingIOError, OSError):
                return

    @staticmethod
    async def _process_rows() -> list[tuple[int, str]]:
        process = await asyncio.create_subprocess_exec(
            "ps",
            "-ax",
            "-o",
            "pid=,command=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        rows: list[tuple[int, str]] = []
        for line in stdout.decode(errors="replace").splitlines():
            match = re.match(r"\s*(\d+)\s+(.*)", line)
            if match:
                rows.append((int(match.group(1)), match.group(2)))
        return rows

    @staticmethod
    def _is_antigravity_process(command_line: str) -> bool:
        normalized = command_line.lower()
        return bool(
            re.search(r"(?:^|/)agy(?:\s|$)", normalized)
            or "antigravity.app/contents/resources/bin/language_server" in normalized
            or ("language_server" in normalized and "antigravity" in normalized)
        )

    @staticmethod
    async def _listening_ports(pid: int) -> list[int]:
        process = await asyncio.create_subprocess_exec(
            "lsof",
            "-nP",
            "-a",
            "-p",
            str(pid),
            "-iTCP",
            "-sTCP:LISTEN",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        return [
            int(match.group(1))
            for match in re.finditer(r":(\d+)\s+\(LISTEN\)", stdout.decode(errors="replace"))
        ]

    @staticmethod
    def _flag_value(command_line: str, flag: str) -> str | None:
        match = re.search(rf"(?:--)?{re.escape(flag)}(?:=|\s+)([^\s]+)", command_line)
        return match.group(1) if match else None

    @staticmethod
    def _parse_user_status(document: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
        if not isinstance(document, Mapping):
            return None, None
        status = document.get("userStatus", document)
        if not isinstance(status, Mapping):
            return None, None
        email = status.get("email")
        observed_email = email.strip() if isinstance(email, str) and email.strip() else None
        tier = status.get("userTier")
        plan_type = tier.get("name") if isinstance(tier, Mapping) else None
        if not isinstance(plan_type, str) or not plan_type.strip():
            plan_status = status.get("planStatus")
            plan_info = plan_status.get("planInfo") if isinstance(plan_status, Mapping) else None
            plan_type = plan_info.get("planName") if isinstance(plan_info, Mapping) else None
        return observed_email, plan_type if isinstance(plan_type, str) else None

    @staticmethod
    def _unavailable(
        account: AccountConfig,
        retrieved_at: datetime,
        error_code: ErrorCode,
        message: str,
        *,
        observed_email: str | None = None,
        source: str = "antigravity_local",
    ) -> UsageSnapshot:
        return UsageSnapshot(
            account_id=account.id,
            provider=account.provider,
            configured_email=account.email,
            observed_email=observed_email,
            status=AccountStatus.UNAVAILABLE,
            source=source,
            retrieved_at=retrieved_at,
            message=message,
            error_code=error_code,
        )
