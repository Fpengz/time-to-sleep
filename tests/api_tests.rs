use axum::body::Body;
use axum::http::{Request, StatusCode};
use std::collections::HashMap;
use std::sync::Arc;
use time_to_sleep::api::{create_router, AppState, EventBroadcaster};
use time_to_sleep::domain::{AccountConfig, ProviderName, Settings};
use time_to_sleep::history::HistoryStore;
use time_to_sleep::services::{AnalyticsService, LoginService, UsageService};
use tokio::sync::RwLock;
use tower::ServiceExt;

fn build_test_app() -> axum::Router {
    let temp_dir = std::env::temp_dir().join(format!("tts_test_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&temp_dir);
    std::env::set_var("TIME_TO_SLEEP_CONFIG_DIR", &temp_dir);

    let settings = Arc::new(RwLock::new(Settings::default()));
    let usage_service = Arc::new(UsageService::new(HashMap::new()));
    let analytics_service = Arc::new(AnalyticsService::new());
    let history_store = Arc::new(HistoryStore::new(None).unwrap());
    let broadcaster = Arc::new(EventBroadcaster::new());
    let login_service = Arc::new(LoginService::new());

    let state = AppState {
        settings,
        usage_service,
        analytics_service,
        history_store,
        broadcaster,
        login_service,
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

#[tokio::test]
async fn test_api_settings_get_and_post() {
    let app = build_test_app();

    // Test GET /v1/settings
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/v1/settings")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let settings: Settings = serde_json::from_slice(&bytes).unwrap();
    assert!(settings.auto_retrieval.enabled);
    assert_eq!(settings.auto_retrieval.poll_interval_secs, 60);

    // Test POST /v1/settings
    let mut updated = settings.clone();
    updated.auto_retrieval.poll_interval_secs = 300;
    updated.auto_retrieval.claude_ttl_secs = 600;

    let post_req = Request::builder()
        .uri("/v1/settings")
        .method("POST")
        .header("Content-Type", "application/json")
        .body(Body::from(serde_json::to_vec(&updated).unwrap()))
        .unwrap();

    let post_resp = app.oneshot(post_req).await.unwrap();
    assert_eq!(post_resp.status(), StatusCode::OK);
    let post_bytes = axum::body::to_bytes(post_resp.into_body(), usize::MAX)
        .await
        .unwrap();
    let saved_settings: Settings = serde_json::from_slice(&post_bytes).unwrap();
    assert_eq!(saved_settings.auto_retrieval.poll_interval_secs, 300);
    assert_eq!(saved_settings.auto_retrieval.claude_ttl_secs, 600);
}

#[tokio::test]
async fn test_api_save_settings_preserves_accounts() {
    let app = build_test_app();

    // 1. Add an account via /v1/accounts/config
    let new_account = AccountConfig {
        id: "codex-test".to_string(),
        provider: ProviderName::Codex,
        email: "test@example.com".to_string(),
        home: "~/.codex".to_string(),
        priority: 0,
        warning_threshold: 80.0,
        auto_retrieval: true,
    };

    let add_req = Request::builder()
        .uri("/v1/accounts/config")
        .method("POST")
        .header("Content-Type", "application/json")
        .body(Body::from(serde_json::to_vec(&new_account).unwrap()))
        .unwrap();

    let add_resp = app.clone().oneshot(add_req).await.unwrap();
    assert_eq!(add_resp.status(), StatusCode::OK);

    // 2. Client sends settings save with empty/stale accounts list
    let empty_accounts_settings = Settings {
        accounts: vec![],
        auto_retrieval: time_to_sleep::domain::AutoRetrievalSettings {
            enabled: true,
            poll_interval_secs: 120,
            ..Default::default()
        },
    };

    let save_req = Request::builder()
        .uri("/v1/settings")
        .method("POST")
        .header("Content-Type", "application/json")
        .body(Body::from(
            serde_json::to_vec(&empty_accounts_settings).unwrap(),
        ))
        .unwrap();

    let save_resp = app.clone().oneshot(save_req).await.unwrap();
    assert_eq!(save_resp.status(), StatusCode::OK);
    let save_bytes = axum::body::to_bytes(save_resp.into_body(), usize::MAX)
        .await
        .unwrap();
    let saved: Settings = serde_json::from_slice(&save_bytes).unwrap();
    assert_eq!(saved.auto_retrieval.poll_interval_secs, 120);
    // Accounts should NOT be wiped out!
    assert_eq!(saved.accounts.len(), 1);
    assert_eq!(saved.accounts[0].id, "codex-test");

    // 3. Verify subsequent GET /v1/settings returns preserved account and updated preferences
    let get_req = Request::builder()
        .uri("/v1/settings")
        .body(Body::empty())
        .unwrap();
    let get_resp = app.oneshot(get_req).await.unwrap();
    let get_bytes = axum::body::to_bytes(get_resp.into_body(), usize::MAX)
        .await
        .unwrap();
    let final_settings: Settings = serde_json::from_slice(&get_bytes).unwrap();
    assert_eq!(final_settings.accounts.len(), 1);
    assert_eq!(final_settings.accounts[0].id, "codex-test");
    assert_eq!(final_settings.auto_retrieval.poll_interval_secs, 120);
}
