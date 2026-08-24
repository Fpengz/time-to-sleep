use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Result;
use clap::{Parser, Subcommand};
use time_to_sleep::api::{create_router, AppState, EventBroadcaster};
use time_to_sleep::cli::{format_prompt, format_table, run_tui};
use time_to_sleep::config::{load_settings, save_settings};
use time_to_sleep::discovery::discover_accounts;
use time_to_sleep::domain::{ProviderName, UsageSnapshot};
use time_to_sleep::history::HistoryStore;
use time_to_sleep::providers::antigravity::AntigravityProvider;
use time_to_sleep::providers::claude::ClaudeProvider;
use time_to_sleep::providers::codex::CodexProvider;
use time_to_sleep::providers::UsageProvider;
use time_to_sleep::services::{AnalyticsService, UsageService};
use tokio::sync::RwLock;

#[derive(Parser)]
#[command(name = "time-to-sleep")]
#[command(about = "High-performance local usage retrieval for AI coding assistants", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    #[arg(short, long, help = "Port to listen or connect to")]
    port: Option<u16>,
}

#[derive(Subcommand)]
enum Commands {
    #[command(about = "Start the backend API server and web dashboard")]
    Serve {
        #[arg(short, long)]
        port: Option<u16>,
    },
    #[command(about = "Print tabular usage ledger in terminal")]
    Status {
        #[arg(short, long)]
        port: Option<u16>,
        #[arg(short = 'f', long, help = "Bypass cached snapshots")]
        force_refresh: bool,
    },
    #[command(about = "Output compact status for shell prompt / statusline")]
    Prompt {
        #[arg(
            long,
            default_value = "compact",
            help = "Format: compact, starship, tmux, json, waybar, sketchybar"
        )]
        format: String,
        #[arg(short, long)]
        port: Option<u16>,
    },
    #[command(about = "Launch interactive terminal dashboard")]
    Tui {
        #[arg(short, long)]
        port: Option<u16>,
    },
    #[command(about = "Scan local system for AI assistant accounts")]
    Discover {
        #[arg(long, help = "Automatically add discovered accounts to configuration")]
        apply: bool,
        #[arg(long, help = "Output results in JSON format")]
        json: bool,
    },
}

fn get_default_port() -> u16 {
    std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(4141)
}

fn build_services() -> (Arc<UsageService>, Arc<AnalyticsService>, Arc<HistoryStore>) {
    let mut providers: HashMap<ProviderName, Arc<dyn UsageProvider>> = HashMap::new();
    providers.insert(ProviderName::Codex, Arc::new(CodexProvider::new()));
    providers.insert(ProviderName::Claude, Arc::new(ClaudeProvider::new()));
    providers.insert(
        ProviderName::Antigravity,
        Arc::new(AntigravityProvider::new()),
    );

    let usage_service = Arc::new(UsageService::new(providers));
    let analytics_service = Arc::new(AnalyticsService::new());
    let history_store = Arc::new(
        HistoryStore::new(Some(&HistoryStore::default_path()))
            .unwrap_or_else(|_| HistoryStore::new(None).unwrap()),
    );

    (usage_service, analytics_service, history_store)
}

async fn fetch_usage_remote_or_local(port: u16, force_refresh: bool) -> Vec<UsageSnapshot> {
    let url = if force_refresh {
        format!("http://127.0.0.1:{}/v1/usage?force_refresh=true", port)
    } else {
        format!("http://127.0.0.1:{}/v1/usage", port)
    };

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(1500))
        .build()
        .unwrap_or_default();

    if let Ok(resp) = client.get(&url).send().await {
        if resp.status().is_success() {
            if let Ok(val) = resp.json::<serde_json::Value>().await {
                if let Some(accs) = val.get("accounts") {
                    if let Ok(snapshots) =
                        serde_json::from_value::<Vec<UsageSnapshot>>(accs.clone())
                    {
                        return snapshots;
                    }
                }
            }
        }
    }

    // Direct in-process fallback
    let settings = load_settings();
    let (usage_service, _, history_store) = build_services();
    let snapshots = usage_service.collect(&settings, force_refresh).await;
    let _ = history_store.record_snapshots(&snapshots);
    snapshots
}

#[tokio::main]
async fn main() -> Result<()> {
    let _ = dotenvy::dotenv();
    let cli = Cli::parse();
    let port = cli.port.unwrap_or_else(get_default_port);

    match cli.command {
        Some(Commands::Serve { port: p }) => {
            let server_port = p.unwrap_or(port);
            let settings = Arc::new(RwLock::new(load_settings()));
            let (usage_service, analytics_service, history_store) = build_services();
            let broadcaster = Arc::new(EventBroadcaster::new());

            let state = AppState {
                settings,
                usage_service,
                analytics_service,
                history_store,
                broadcaster,
            };

            let app = create_router(state);
            let addr = SocketAddr::from(([127, 0, 0, 1], server_port));
            println!(
                "🚀 time-to-sleep running at http://127.0.0.1:{}",
                server_port
            );
            let listener = tokio::net::TcpListener::bind(addr).await?;
            axum::serve(listener, app).await?;
        }
        Some(Commands::Status {
            port: p,
            force_refresh,
        }) => {
            let target_port = p.unwrap_or(port);
            let snapshots = fetch_usage_remote_or_local(target_port, force_refresh).await;
            print!("{}", format_table(&snapshots));
        }
        Some(Commands::Prompt { format, port: p }) => {
            let target_port = p.unwrap_or(port);
            let snapshots = fetch_usage_remote_or_local(target_port, false).await;
            println!("{}", format_prompt(&snapshots, &format));
        }
        Some(Commands::Tui { port: p }) => {
            let target_port = p.unwrap_or(port);
            run_tui(target_port).await?;
        }
        Some(Commands::Discover { apply, json }) => {
            let settings = load_settings();
            let existing_ids: Vec<&str> = settings.accounts.iter().map(|a| a.id.as_str()).collect();
            let discovered = discover_accounts(&existing_ids);

            if json {
                println!("{}", serde_json::to_string_pretty(&discovered)?);
            } else if discovered.is_empty() {
                println!("No new AI assistant accounts discovered.");
            } else {
                println!("Discovered {} new account(s):", discovered.len());
                for acc in &discovered {
                    println!(
                        "  • {} ({}): {} [{}]",
                        acc.provider.display_name(),
                        acc.id,
                        acc.email,
                        acc.home
                    );
                }

                if apply {
                    let mut new_settings = settings;
                    new_settings.accounts.extend(discovered);
                    save_settings(&new_settings)?;
                    println!("\nSuccessfully added accounts to configuration.");
                } else {
                    println!("\nRun with '--apply' to automatically add these accounts.");
                }
            }
        }
        None => {
            // Default: start serve
            let settings = Arc::new(RwLock::new(load_settings()));
            let (usage_service, analytics_service, history_store) = build_services();
            let broadcaster = Arc::new(EventBroadcaster::new());

            let state = AppState {
                settings,
                usage_service,
                analytics_service,
                history_store,
                broadcaster,
            };

            let app = create_router(state);
            let addr = SocketAddr::from(([127, 0, 0, 1], port));
            println!("🚀 time-to-sleep running at http://127.0.0.1:{}", port);
            let listener = tokio::net::TcpListener::bind(addr).await?;
            axum::serve(listener, app).await?;
        }
    }

    Ok(())
}
