use axum::body::Body;
use axum::http::{Request, StatusCode};
use std::collections::HashMap;
use std::sync::Arc;
use time_to_sleep::api::{create_router, AppState, EventBroadcaster};
use time_to_sleep::domain::Settings;
use time_to_sleep::history::HistoryStore;
use time_to_sleep::services::{AnalyticsService, UsageService};
use tokio::sync::RwLock;
use tower::ServiceExt;

fn build_test_app() -> axum::Router {
    let settings = Arc::new(RwLock::new(Settings::default()));
    let usage_service = Arc::new(UsageService::new(HashMap::new()));
    let analytics_service = Arc::new(AnalyticsService::new());
    let history_store = Arc::new(HistoryStore::new(None).unwrap());
    let broadcaster = Arc::new(EventBroadcaster::new());

    let state = AppState {
        settings,
        usage_service,
        analytics_service,
        history_store,
        broadcaster,
    };

    create_router(state)
}

#[tokio::test]
async fn test_api_usage_endpoint() {
    let app = build_test_app();
    let response = app
        .oneshot(
            Request::builder()
                .uri("/v1/usage")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let val: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert!(val.get("accounts").is_some());
    assert!(val.get("generated_at").is_some());
}

#[tokio::test]
async fn test_api_analytics_endpoint() {
    let app = build_test_app();
    let response = app
        .oneshot(
            Request::builder()
                .uri("/v1/analytics")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let val: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert!(val.get("accounts").is_some());
}

#[tokio::test]
async fn test_api_static_index() {
    let app = build_test_app();
    let response = app
        .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
}
