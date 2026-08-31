use std::collections::HashMap;
use std::sync::Arc;

use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use time_to_sleep::api::{create_router, AppState, EventBroadcaster};
use time_to_sleep::domain::Settings;
use time_to_sleep::history::HistoryStore;
use time_to_sleep::services::{AnalyticsService, LoginService, UsageService};
use tokio::sync::RwLock;
use tower::ServiceExt;

fn build_test_app() -> axum::Router {
    let settings = Arc::new(RwLock::new(Settings::default()));
    let usage_service = Arc::new(UsageService::new(HashMap::new()));
    let analytics_service = Arc::new(AnalyticsService::new());
    let history_store = Arc::new(HistoryStore::new(None).unwrap());
    let broadcaster = Arc::new(EventBroadcaster::new());
    let login_service = Arc::new(LoginService::new());

    create_router(AppState {
        settings,
        usage_service,
        analytics_service,
        history_store,
        broadcaster,
        login_service,
    })
}

#[tokio::test]
async fn redesign_assets_are_embedded_and_served() {
    for uri in ["/static/redesign.css", "/static/redesign.js"] {
        let response = build_test_app()
            .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK, "{uri}");

        let content_type = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default();

        if uri.ends_with(".css") {
            assert!(content_type.starts_with("text/css"), "{uri}: {content_type}");
        } else {
            assert!(
                content_type.starts_with("text/javascript")
                    || content_type.starts_with("application/javascript"),
                "{uri}: {content_type}"
            );
        }
    }
}
