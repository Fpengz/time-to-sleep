use std::io::stdout;
use std::time::{Duration, Instant};

use anyhow::Result;
use crossterm::event::{self, Event, KeyCode};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::widgets::{Block, Borders, Paragraph, Row, Table};
use ratatui::Terminal;

use crate::domain::UsageSnapshot;

pub async fn run_tui(port: u16) -> Result<()> {
    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut last_refresh = Instant::now() - Duration::from_secs(60);
    let mut snapshots: Vec<UsageSnapshot> = Vec::new();
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{}/v1/usage", port);

    loop {
        if last_refresh.elapsed() >= Duration::from_secs(10) {
            if let Ok(resp) = client.get(&url).send().await {
                if let Ok(val) = resp.json::<serde_json::Value>().await {
                    if let Some(accs) = val.get("accounts") {
                        if let Ok(parsed) =
                            serde_json::from_value::<Vec<UsageSnapshot>>(accs.clone())
                        {
                            snapshots = parsed;
                        }
                    }
                }
            }
            last_refresh = Instant::now();
        }

        terminal.draw(|f| {
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .margin(1)
                .constraints([
                    Constraint::Length(3),
                    Constraint::Min(6),
                    Constraint::Length(3),
                ])
                .split(f.area());

            let title = Paragraph::new(" TIME-TO-SLEEP — Live Quota & Usage Monitor")
                .style(
                    Style::default()
                        .fg(Color::Cyan)
                        .add_modifier(Modifier::BOLD),
                )
                .block(Block::default().borders(Borders::ALL));
            f.render_widget(title, chunks[0]);

            let rows: Vec<Row> = snapshots
                .iter()
                .map(|s| {
                    let max_pct = s.max_used_percent().unwrap_or(0.0);
                    let color = if max_pct >= 90.0 {
                        Color::Red
                    } else if max_pct >= 75.0 {
                        Color::Yellow
                    } else {
                        Color::Green
                    };
                    Row::new(vec![
                        s.account_id.clone(),
                        s.provider.display_name().to_string(),
                        s.status.as_str().to_string(),
                        format!("{:.1}%", max_pct),
                    ])
                    .style(Style::default().fg(color))
                })
                .collect();

            let table = Table::new(
                rows,
                [
                    Constraint::Percentage(30),
                    Constraint::Percentage(25),
                    Constraint::Percentage(25),
                    Constraint::Percentage(20),
                ],
            )
            .header(
                Row::new(vec!["Account", "Provider", "Status", "Usage"])
                    .style(Style::default().add_modifier(Modifier::BOLD)),
            )
            .block(Block::default().borders(Borders::ALL).title(" Accounts "));
            f.render_widget(table, chunks[1]);

            let help = Paragraph::new("Press 'r' to force refresh, 'q' to quit.")
                .style(Style::default().fg(Color::DarkGray))
                .block(Block::default().borders(Borders::ALL));
            f.render_widget(help, chunks[2]);
        })?;

        if event::poll(Duration::from_millis(250))? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') | KeyCode::Esc => break,
                    KeyCode::Char('r') => {
                        last_refresh = Instant::now() - Duration::from_secs(60);
                    }
                    _ => {}
                }
            }
        }
    }

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}
