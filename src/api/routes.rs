use std::convert::Infallible;
use std::path::Path as FsPath;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use chrono::Utc;
use futures::stream::Stream;
use rust_embed::RustEmbed;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::RwLock;
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::StreamExt;
use tower_http::cors::{Any, CorsLayer};

use super::sse::EventBroadcaster;
use crate::config::save_settings;
use crate::discovery::discover_accounts;
use crate::domain::{
    AccountConfig, AccountStatus, AccountStatusView, AnalyticsResponse, HistoryPoint,
    HourlyUsageDistribution, LoginAttempt, LoginChallenge, Settings,
};
use crate::history::HistoryStore;
use crate::services::{AnalyticsService, LoginError, LoginService, UsageService};

#[derive(RustEmbed)]
#[folder = "static/"]
struct StaticAssets;

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<RwLock<Settings>>,
    pub usage_service: Arc<UsageService>,
    pub analytics_service: Arc<AnalyticsService>,
    pub history_store: Arc<HistoryStore>,
    pub broadcaster: Arc<EventBroadcaster>,
    pub login_service: Arc<LoginService>,
}

pub struct ApiError {
    status: StatusCode,
    detail: String,
}

impl ApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

impl From<LoginError> for ApiError {
    fn from(error: LoginError) -> Self {
        match error {
            LoginError::AccountNotFound => {
                ApiError::new(StatusCode::NOT_FOUND, "Account not found")
            }
            LoginError::AttemptNotFound => {
                ApiError::new(StatusCode::NOT_FOUND, "Login attempt not found")
            }
            LoginError::Conflict(msg) => ApiError::new(StatusCode::CONFLICT, msg),
            LoginError::Internal(msg) => {
                ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, msg)
            }
        }
    }
}

#[derive(Deserialize)]
pub struct UsageParams {
    #[serde(default)]
    pub force_refresh: bool,
}

pub async fn usage_handler(
    State(state): State<AppState>,
    Query(params): Query<UsageParams>,
) -> Json<serde_json::Value> {
    let settings = state.settings.read().await.clone();
    let snapshots = state
        .usage_service
        .collect(&settings, params.force_refresh)
        .await;
    let analytics_data = state.analytics_service.analyze(&snapshots, Some(&settings));

    let _ = state.history_store.record_snapshots(&snapshots);

    if state.broadcaster.has_subscribers() {
        let usage_payload = json!({
            "generated_at": Utc::now(),
            "accounts": snapshots,
        });
        state.broadcaster.broadcast("usage", &usage_payload);
        if let Ok(val) = serde_json::to_value(&analytics_data) {
            state.broadcaster.broadcast("analytics", &val);
        }
    }

    Json(json!({
        "generated_at": Utc::now(),
        "accounts": snapshots,
    }))
}

pub async fn analytics_handler(State(state): State<AppState>) -> Json<AnalyticsResponse> {
    let settings = state.settings.read().await.clone();
    let snapshots = state.usage_service.collect(&settings, false).await;
    let analytics = state.analytics_service.analyze(&snapshots, Some(&settings));
    Json(analytics)
}

#[derive(Deserialize)]
pub struct HistoryParams {
    pub account_id: Option<String>,
    #[serde(default = "default_history_hours")]
    pub hours: i64,
}

fn default_history_hours() -> i64 {
    24
}

pub async fn history_handler(
    State(state): State<AppState>,
    Query(params): Query<HistoryParams>,
) -> Json<Vec<HistoryPoint>> {
    let points = state
        .history_store
        .get_history(params.account_id.as_deref(), params.hours)
        .unwrap_or_default();
    Json(points)
}

#[derive(Deserialize)]
pub struct HeatmapParams {
    pub account_id: Option<String>,
    #[serde(default = "default_heatmap_days")]
    pub days: i64,
}

fn default_heatmap_days() -> i64 {
    7
}

pub async fn heatmap_handler(
    State(state): State<AppState>,
    Query(params): Query<HeatmapParams>,
) -> Json<Vec<HourlyUsageDistribution>> {
    let heatmap = state
        .history_store
        .get_hourly_heatmap(params.account_id.as_deref(), params.days)
        .unwrap_or_default();
    Json(heatmap)
}

pub async fn events_handler(
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let settings = state.settings.read().await.clone();
    let snapshots = state.usage_service.collect(&settings, false).await;
    let analytics_data = state.analytics_service.analyze(&snapshots, Some(&settings));

    let rx = state.broadcaster.subscribe();
    let broadcast_stream = BroadcastStream::new(rx)
        .filter_map(|res| res.ok())
        .map(|msg| Ok(Event::default().data(msg)));

    let init_usage_event = Event::default().event("usage").data(
        json!({
            "generated_at": Utc::now(),
            "accounts": snapshots,
        })
        .to_string(),
    );

    let init_analytics_event = Event::default()
        .event("analytics")
        .data(serde_json::to_string(&analytics_data).unwrap_or_default());

    let initial_stream =
        futures::stream::iter(vec![Ok(init_usage_event), Ok(init_analytics_event)]);

    let full_stream = initial_stream.chain(broadcast_stream);

    Sse::new(full_stream).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(20))
            .text("keepalive"),
    )
}

pub async fn accounts_handler(State(state): State<AppState>) -> Json<Vec<AccountStatusView>> {
    let settings = state.settings.read().await.clone();
    let mut views = Vec::with_capacity(settings.accounts.len());
    for account in &settings.accounts {
        let cached = state.usage_service.get_cached(&account.id).await;
        let ready = match &cached {
            Some(snapshot) => snapshot.status != AccountStatus::Unavailable,
            None => FsPath::new(&account.expanded_home()).exists(),
        };
        views.push(AccountStatusView {
            account_id: account.id.clone(),
            provider: account.provider,
            configured_email: account.email.clone(),
            configured_home: account.home.clone(),
            ready,
            observed_email: cached.as_ref().and_then(|s| s.observed_email.clone()),
            message: cached.as_ref().and_then(|s| s.message.clone()),
        });
    }
    Json(views)
}

pub async fn discover_handler(State(state): State<AppState>) -> Json<Vec<AccountConfig>> {
    let settings = state.settings.read().await.clone();
    let existing: Vec<&str> = settings.accounts.iter().map(|a| a.id.as_str()).collect();
    Json(discover_accounts(&existing))
}

#[derive(Deserialize)]
pub struct DiscoverApplyRequest {
    #[serde(default)]
    pub account_ids: Option<Vec<String>>,
}

pub async fn discover_apply_handler(
    State(state): State<AppState>,
    Json(req): Json<DiscoverApplyRequest>,
) -> Result<Json<Vec<AccountConfig>>, ApiError> {
    let mut settings = state.settings.write().await;
    let existing: Vec<&str> = settings.accounts.iter().map(|a| a.id.as_str()).collect();
    let mut candidates = discover_accounts(&existing);
    if let Some(ids) = req.account_ids {
        let id_set: std::collections::HashSet<String> = ids.into_iter().collect();
        candidates.retain(|c| id_set.contains(&c.id));
    }

    if candidates.is_empty() {
        return Ok(Json(settings.accounts.clone()));
    }

    settings.accounts.extend(candidates);
    save_settings(&settings)
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(settings.accounts.clone()))
}

pub async fn save_account_config_handler(
    State(state): State<AppState>,
    Json(account): Json<AccountConfig>,
) -> Result<Json<Vec<AccountConfig>>, ApiError> {
    let mut settings = state.settings.write().await;
    settings.accounts.retain(|a| a.id != account.id);
    settings.accounts.push(account);
    save_settings(&settings)
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(settings.accounts.clone()))
}

pub async fn delete_account_config_handler(
    State(state): State<AppState>,
    Path(account_id): Path<String>,
) -> Result<Json<Vec<AccountConfig>>, ApiError> {
    let mut settings = state.settings.write().await;
    let before = settings.accounts.len();
    let filtered: Vec<AccountConfig> = settings
        .accounts
        .iter()
        .filter(|a| a.id != account_id)
        .cloned()
        .collect();
    if filtered.len() == before {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "Account not found"));
    }
    if filtered.is_empty() {
        return Err(ApiError::new(
            StatusCode::BAD_REQUEST,
            "Cannot delete the last remaining account",
        ));
    }
    settings.accounts = filtered;
    save_settings(&settings)
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(settings.accounts.clone()))
}

#[derive(Deserialize)]
pub struct LoginStartRequest {
    pub method: String,
}

pub async fn login_start_handler(
    State(state): State<AppState>,
    Path(account_id): Path<String>,
    Json(req): Json<LoginStartRequest>,
) -> Result<(StatusCode, Json<LoginChallenge>), ApiError> {
    let settings = state.settings.read().await.clone();
    let challenge = state
        .login_service
        .start(&settings, &account_id, &req.method)
        .await?;
    Ok((StatusCode::ACCEPTED, Json(challenge)))
}

pub async fn login_status_handler(
    State(state): State<AppState>,
    Path((account_id, attempt_id)): Path<(String, String)>,
) -> Result<Json<LoginAttempt>, ApiError> {
    let attempt = state.login_service.status(&account_id, &attempt_id).await?;
    Ok(Json(attempt))
}

pub async fn login_cancel_handler(
    State(state): State<AppState>,
    Path((account_id, attempt_id)): Path<(String, String)>,
) -> Result<Json<LoginAttempt>, ApiError> {
    let attempt = state.login_service.cancel(&account_id, &attempt_id).await?;
    Ok(Json(attempt))
}

pub async fn static_handler(axum::extract::Path(path): axum::extract::Path<String>) -> Response {
    let raw = path.trim_start_matches('/');
    let target = if raw.is_empty() {
        "index.html"
    } else if let Some(stripped) = raw.strip_prefix("static/") {
        stripped
    } else {
        raw
    };

    if let Some(asset) = StaticAssets::get(target) {
        let mime = mime_guess::from_path(target).first_or_octet_stream();
        let mut headers = HeaderMap::new();
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_str(mime.as_ref()).unwrap(),
        );
        (StatusCode::OK, headers, asset.data).into_response()
    } else if let Some(asset) = StaticAssets::get("index.html") {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("text/html; charset=utf-8"),
        );
        (StatusCode::OK, headers, asset.data).into_response()
    } else {
        (StatusCode::NOT_FOUND, "Not Found").into_response()
    }
}

pub async fn index_handler() -> Response {
    static_handler(axum::extract::Path("index.html".to_string())).await
}

pub fn create_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        .route("/v1/usage", get(usage_handler))
        .route("/v1/analytics", get(analytics_handler))
        .route("/v1/history", get(history_handler))
        .route("/v1/analytics/heatmap", get(heatmap_handler))
        .route("/v1/events", get(events_handler))
        .route("/v1/accounts", get(accounts_handler))
        .route("/v1/accounts/discover", get(discover_handler))
        .route("/v1/accounts/discover/apply", post(discover_apply_handler))
        .route("/v1/accounts/config", post(save_account_config_handler))
        .route(
            "/v1/accounts/config/{account_id}",
            delete(delete_account_config_handler),
        )
        .route(
            "/v1/accounts/{account_id}/login/start",
            post(login_start_handler),
        )
        .route(
            "/v1/accounts/{account_id}/login/{attempt_id}",
            get(login_status_handler),
        )
        .route(
            "/v1/accounts/{account_id}/login/{attempt_id}/cancel",
            post(login_cancel_handler),
        )
        .route("/", get(index_handler))
        .route("/{*path}", get(static_handler))
        .layer(cors)
        .with_state(state)
}
