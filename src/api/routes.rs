use std::convert::Infallible;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
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
use crate::domain::{AnalyticsResponse, HistoryPoint, HourlyUsageDistribution, Settings};
use crate::history::HistoryStore;
use crate::services::{AnalyticsService, UsageService};

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
        .route("/", get(index_handler))
        .route("/{*path}", get(static_handler))
        .layer(cors)
        .with_state(state)
}
