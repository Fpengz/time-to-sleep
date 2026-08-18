from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from time_to_sleep import __version__
from time_to_sleep.config import load_settings
from time_to_sleep.domain import (
    AccountStatusView,
    LoginAttempt,
    LoginChallenge,
    Settings,
    UsageSnapshot,
)
from time_to_sleep.providers.antigravity import AntigravityProvider
from time_to_sleep.providers.claude import ClaudeProvider
from time_to_sleep.providers.codex import CodexProvider
from time_to_sleep.services import LoginService, ProviderRegistry, UsageService

app = FastAPI(title="Time-to-Sleep Usage Backend", version=__version__)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _build_services() -> tuple[Settings, UsageService, LoginService]:
    settings = load_settings()
    providers = ProviderRegistry(
        {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
            "antigravity": AntigravityProvider(),
        }
    )
    return settings, UsageService(settings, providers), LoginService(settings)


_settings, _usage_service, _login_service = _build_services()


def get_settings() -> Settings:
    return _settings


def get_usage_service() -> UsageService:
    return _usage_service


def get_login_service() -> LoginService:
    return _login_service


class LoginStartRequest(BaseModel):
    method: Literal["browser", "device_code"]


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return {"status": "ok", "configured_accounts": len(settings.accounts)}


@app.get("/v1/accounts")
async def accounts(
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> list[AccountStatusView]:
    return await service.account_statuses()


@app.get("/v1/usage")
async def usage(
    service: Annotated[UsageService, Depends(get_usage_service)],
    force_refresh: bool = False,
) -> dict[str, object]:
    snapshots: list[UsageSnapshot] = await service.collect(force_refresh=force_refresh)
    return {"generated_at": datetime.now(UTC), "accounts": snapshots}


@app.post(
    "/v1/accounts/{account_id}/login/start",
    response_model=LoginChallenge,
    status_code=status.HTTP_202_ACCEPTED,
)
async def login_start(
    account_id: str,
    request: LoginStartRequest,
    service: Annotated[LoginService, Depends(get_login_service)],
) -> LoginChallenge:
    try:
        return await service.start(account_id, request.method)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Account not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/v1/accounts/{account_id}/login/{attempt_id}",
    response_model=LoginAttempt,
)
async def login_status(
    account_id: str,
    attempt_id: str,
    service: Annotated[LoginService, Depends(get_login_service)],
) -> LoginAttempt:
    try:
        return await service.status(account_id, attempt_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Login attempt not found") from error


@app.post(
    "/v1/accounts/{account_id}/login/{attempt_id}/cancel",
    response_model=LoginAttempt,
)
async def login_cancel(
    account_id: str,
    attempt_id: str,
    service: Annotated[LoginService, Depends(get_login_service)],
) -> LoginAttempt:
    try:
        return await service.cancel(account_id, attempt_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Login attempt not found") from error
