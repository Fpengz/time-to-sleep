import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from time_to_sleep import __version__
from time_to_sleep.config import load_settings, save_settings
from time_to_sleep.discovery import discover_accounts
from time_to_sleep.domain import (
    AccountConfig,
    AccountStatusView,
    AnalyticsResponse,
    LoginAttempt,
    LoginChallenge,
    Settings,
    UsageSnapshot,
)
from time_to_sleep.history import (
    HistoryPoint,
    HistoryStore,
    HourlyUsageDistribution,
    default_history_store,
)
from time_to_sleep.providers.antigravity import AntigravityProvider
from time_to_sleep.providers.claude import ClaudeProvider
from time_to_sleep.providers.codex import CodexProvider
from time_to_sleep.services import (
    AnalyticsService,
    LoginService,
    ProviderRegistry,
    UsageService,
)

app = FastAPI(title="Time-to-Sleep Usage Backend", version=__version__)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    async def broadcast(self, event_type: str, data: Any) -> None:
        if not self._subscribers:
            return

        def _json_serial(obj: Any) -> str:
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        payload = json.dumps(data, default=_json_serial)
        msg = f"event: {event_type}\ndata: {payload}\n\n"
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                self.unsubscribe(q)


_broadcaster = EventBroadcaster()
_history_store = default_history_store


def _build_services() -> tuple[Settings, UsageService, LoginService, AnalyticsService]:
    settings = load_settings()
    providers = ProviderRegistry(
        {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
            "antigravity": AntigravityProvider(),
        }
    )
    return (
        settings,
        UsageService(settings, providers),
        LoginService(settings),
        AnalyticsService(),
    )


_settings, _usage_service, _login_service, _analytics_service = _build_services()


def reload_services() -> None:
    global _settings, _usage_service, _login_service, _analytics_service
    _settings, _usage_service, _login_service, _analytics_service = _build_services()


def get_settings() -> Settings:
    return _settings


def get_usage_service() -> UsageService:
    return _usage_service


def get_login_service() -> LoginService:
    return _login_service


def get_analytics_service() -> AnalyticsService:
    return _analytics_service


def get_broadcaster() -> EventBroadcaster:
    return _broadcaster


def get_history_store() -> HistoryStore:
    return _history_store


class LoginStartRequest(BaseModel):
    method: Literal["browser", "device_code"]


class AutoDiscoverApplyRequest(BaseModel):
    account_ids: list[str] | None = None


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


@app.get("/v1/accounts/discover", response_model=list[AccountConfig])
async def discover_candidate_accounts(
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[AccountConfig]:
    existing_ids = {a.id for a in settings.accounts}
    return discover_accounts(existing_ids)


@app.post("/v1/accounts/discover/apply", response_model=list[AccountConfig])
async def apply_discovered_accounts(
    request: AutoDiscoverApplyRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[AccountConfig]:
    existing_ids = {a.id for a in settings.accounts}
    candidates = discover_accounts(existing_ids)
    if request.account_ids is not None:
        selected_ids = set(request.account_ids)
        candidates = [c for c in candidates if c.id in selected_ids]

    if not candidates:
        return settings.accounts

    new_accounts = list(settings.accounts) + candidates
    new_settings = Settings(accounts=new_accounts)
    save_settings(new_settings)
    reload_services()
    return new_settings.accounts


@app.post("/v1/accounts/config", response_model=list[AccountConfig])
async def save_account_config(
    account: AccountConfig,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[AccountConfig]:
    updated_accounts = [a for a in settings.accounts if a.id != account.id]
    updated_accounts.append(account)
    new_settings = Settings(accounts=updated_accounts)
    save_settings(new_settings)
    reload_services()
    return new_settings.accounts


@app.delete("/v1/accounts/config/{account_id}", response_model=list[AccountConfig])
async def delete_account_config(
    account_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[AccountConfig]:
    filtered = [a for a in settings.accounts if a.id != account_id]
    if len(filtered) == len(settings.accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    if not filtered:
        raise HTTPException(status_code=400, detail="Cannot delete the last remaining account")
    new_settings = Settings(accounts=filtered)
    save_settings(new_settings)
    reload_services()
    return new_settings.accounts


@app.get("/v1/history", response_model=list[HistoryPoint])
async def get_history(
    history_store: Annotated[HistoryStore, Depends(get_history_store)],
    account_id: str | None = None,
    hours: int = 24,
) -> list[HistoryPoint]:
    return history_store.get_history(account_id=account_id, hours=hours)


@app.get("/v1/analytics/heatmap", response_model=list[HourlyUsageDistribution])
async def get_heatmap(
    history_store: Annotated[HistoryStore, Depends(get_history_store)],
    account_id: str | None = None,
    days: int = 7,
) -> list[HourlyUsageDistribution]:
    return history_store.get_hourly_heatmap(account_id=account_id, days=days)


@app.get("/v1/usage")
async def usage(
    service: Annotated[UsageService, Depends(get_usage_service)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    broadcaster: Annotated[EventBroadcaster, Depends(get_broadcaster)],
    history_store: Annotated[HistoryStore, Depends(get_history_store)],
    force_refresh: bool = False,
) -> dict[str, object]:
    snapshots: list[UsageSnapshot] = await service.collect(force_refresh=force_refresh)
    analytics_data = analytics.analyze(snapshots, settings=settings)
    history_store.record_snapshots(snapshots)
    if broadcaster.has_subscribers:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "accounts": [s.model_dump(mode="json") for s in snapshots],
        }
        await broadcaster.broadcast("usage", payload)
        await broadcaster.broadcast("analytics", analytics_data.model_dump(mode="json"))
    return {"generated_at": datetime.now(UTC), "accounts": snapshots}


@app.get("/v1/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    service: Annotated[UsageService, Depends(get_usage_service)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalyticsResponse:
    snapshots: list[UsageSnapshot] = await service.collect(force_refresh=False)
    return analytics.analyze(snapshots, settings=settings)


@app.get("/v1/events")
async def events_stream(
    request: Request,
    service: Annotated[UsageService, Depends(get_usage_service)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    broadcaster: Annotated[EventBroadcaster, Depends(get_broadcaster)],
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        queue = broadcaster.subscribe()
        try:
            # Send initial state immediately
            snapshots = await service.collect(force_refresh=False)
            analytics_data = analytics.analyze(snapshots, settings=settings)

            def _json_serial(obj: Any) -> str:
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            init_payload = json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "accounts": [s.model_dump(mode="json") for s in snapshots],
                }
            )
            analytics_payload = json.dumps(analytics_data.model_dump(mode="json"))
            yield f"event: usage\ndata: {init_payload}\n\n"
            yield f"event: analytics\ndata: {analytics_payload}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield msg
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    except OSError as error:
        raise HTTPException(
            status_code=500, detail=f"Permission denied or IO error: {error}"
        ) from error


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
