use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, Lines};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{Mutex, RwLock};
use tokio::time::timeout;
use uuid::Uuid;

use crate::domain::{
    AccountConfig, LoginAttempt, LoginChallenge, LoginMethod, LoginStatus, ProviderName, Settings,
};

#[derive(Debug, thiserror::Error)]
pub enum LoginError {
    #[error("account not found")]
    AccountNotFound,
    #[error("login attempt not found")]
    AttemptNotFound,
    #[error("{0}")]
    Conflict(String),
    #[error("{0}")]
    Internal(String),
}

struct Session {
    stdin: Arc<Mutex<ChildStdin>>,
    child: Arc<Mutex<Child>>,
    login_id: Option<String>,
}

struct LoginRecord {
    attempt: LoginAttempt,
    session: Option<Session>,
    monitor: Option<tokio::task::JoinHandle<()>>,
}

type RecordMap = Arc<RwLock<HashMap<(String, String), LoginRecord>>>;

pub struct LoginService {
    command: String,
    records: RecordMap,
    attempt_ttl: ChronoDuration,
}

impl Default for LoginService {
    fn default() -> Self {
        Self::new()
    }
}

impl LoginService {
    pub fn new() -> Self {
        Self {
            command: "codex".to_string(),
            records: Arc::new(RwLock::new(HashMap::new())),
            attempt_ttl: ChronoDuration::minutes(10),
        }
    }

    pub async fn start(
        &self,
        settings: &Settings,
        account_id: &str,
        method_str: &str,
    ) -> Result<LoginChallenge, LoginError> {
        let account = settings
            .accounts
            .iter()
            .find(|a| a.id == account_id)
            .cloned()
            .ok_or(LoginError::AccountNotFound)?;

        if account.provider != ProviderName::Codex {
            return Err(LoginError::Conflict(
                "Login setup is only supported for Codex accounts".to_string(),
            ));
        }

        let method = match method_str {
            "browser" => LoginMethod::Browser,
            "device_code" => LoginMethod::DeviceCode,
            other => {
                return Err(LoginError::Conflict(format!(
                    "Unsupported login method: {other}"
                )))
            }
        };

        let expanded_home = account.expanded_home();
        std::fs::create_dir_all(&expanded_home)
            .map_err(|e| LoginError::Internal(format!("failed to create home dir: {e}")))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = std::fs::metadata(&expanded_home) {
                let mut perms = meta.permissions();
                perms.set_mode(0o700);
                let _ = std::fs::set_permissions(&expanded_home, perms);
            }
        }

        let mut child = Command::new(&self.command)
            .arg("app-server")
            .env("CODEX_HOME", &expanded_home)
            .env("PATH", crate::providers::codex::extended_path_env())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| LoginError::Internal(format!("failed to launch codex: {e}")))?;

        let mut raw_stdin = child
            .stdin
            .take()
            .ok_or_else(|| LoginError::Internal("failed to open codex stdin".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| LoginError::Internal("failed to open codex stdout".to_string()))?;
        let mut reader = BufReader::new(stdout).lines();

        let handshake_timeout = Duration::from_secs(10);

        write_message(
            &mut raw_stdin,
            &json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "time-to-sleep", "version": env!("CARGO_PKG_VERSION")}}
            }),
        )
        .await?;
        wait_for_response(&mut reader, 1, handshake_timeout).await?;

        write_message(
            &mut raw_stdin,
            &json!({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
        )
        .await?;

        let login_type = match method {
            LoginMethod::Browser => "chatgpt",
            LoginMethod::DeviceCode => "chatgptDeviceCode",
        };
        write_message(
            &mut raw_stdin,
            &json!({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "account/login/start",
                "params": {"type": login_type}
            }),
        )
        .await?;
        let result = wait_for_response(&mut reader, 2, handshake_timeout).await?;

        let login_id = result
            .get("loginId")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let auth_url = result
            .get("authUrl")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let verification_url = result
            .get("verificationUrl")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let user_code = result
            .get("userCode")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let attempt_id = Uuid::new_v4().simple().to_string();
        let started_at = Utc::now();
        let expires_at = started_at + self.attempt_ttl;

        let attempt = LoginAttempt {
            attempt_id: attempt_id.clone(),
            account_id: account.id.clone(),
            method,
            status: LoginStatus::Pending,
            started_at,
            expires_at,
            observed_email: None,
            message: None,
        };

        let stdin = Arc::new(Mutex::new(raw_stdin));
        let child = Arc::new(Mutex::new(child));

        let session = Session {
            stdin: stdin.clone(),
            child: child.clone(),
            login_id: login_id.clone(),
        };

        let key = (account.id.clone(), attempt_id.clone());
        {
            let mut records = self.records.write().await;
            records.insert(
                key.clone(),
                LoginRecord {
                    attempt: attempt.clone(),
                    session: Some(session),
                    monitor: None,
                },
            );
        }

        let records_ref = self.records.clone();
        let monitor_key = key.clone();
        let handle = tokio::spawn(monitor_login(
            records_ref,
            monitor_key,
            reader,
            stdin,
            child,
            login_id,
            account,
            expires_at,
        ));

        {
            let mut records = self.records.write().await;
            if let Some(record) = records.get_mut(&key) {
                record.monitor = Some(handle);
            }
        }

        Ok(LoginChallenge {
            attempt_id,
            method,
            status: LoginStatus::Pending,
            auth_url,
            verification_url,
            user_code,
            message: None,
        })
    }

    pub async fn status(
        &self,
        account_id: &str,
        attempt_id: &str,
    ) -> Result<LoginAttempt, LoginError> {
        let key = (account_id.to_string(), attempt_id.to_string());
        let mut records = self.records.write().await;
        let record = records.get_mut(&key).ok_or(LoginError::AttemptNotFound)?;
        if record.attempt.status == LoginStatus::Pending && Utc::now() >= record.attempt.expires_at
        {
            record.attempt.status = LoginStatus::Expired;
            record.attempt.message = Some("Login attempt expired.".to_string());
        }
        Ok(record.attempt.clone())
    }

    pub async fn cancel(
        &self,
        account_id: &str,
        attempt_id: &str,
    ) -> Result<LoginAttempt, LoginError> {
        let key = (account_id.to_string(), attempt_id.to_string());
        let (session, monitor, was_pending) = {
            let mut records = self.records.write().await;
            let record = records.get_mut(&key).ok_or(LoginError::AttemptNotFound)?;
            let was_pending = record.attempt.status == LoginStatus::Pending;
            if was_pending {
                record.attempt.status = LoginStatus::Cancelled;
                record.attempt.message = Some("Login cancelled.".to_string());
            }
            (record.session.take(), record.monitor.take(), was_pending)
        };

        if was_pending {
            if let Some(session) = &session {
                if let Some(login_id) = &session.login_id {
                    let mut stdin = session.stdin.lock().await;
                    let _ = write_message(
                        &mut stdin,
                        &json!({
                            "jsonrpc": "2.0",
                            "id": 99,
                            "method": "account/login/cancel",
                            "params": {"loginId": login_id}
                        }),
                    )
                    .await;
                }
            }
            if let Some(handle) = monitor {
                handle.abort();
            }
            if let Some(session) = session {
                let mut child = session.child.lock().await;
                let _ = child.kill().await;
            }
        }

        let records = self.records.read().await;
        records
            .get(&key)
            .map(|r| r.attempt.clone())
            .ok_or(LoginError::AttemptNotFound)
    }
}

#[allow(clippy::too_many_arguments)]
async fn monitor_login(
    records: RecordMap,
    key: (String, String),
    mut reader: Lines<BufReader<ChildStdout>>,
    stdin: Arc<Mutex<ChildStdin>>,
    child: Arc<Mutex<Child>>,
    login_id: Option<String>,
    _account: AccountConfig,
    expires_at: DateTime<Utc>,
) {
    let remaining = (expires_at - Utc::now())
        .to_std()
        .unwrap_or(Duration::from_secs(0));

    let outcome = timeout(remaining, wait_for_completion(&mut reader, &login_id)).await;

    let (final_status, message, observed_email) = match outcome {
        Ok(Ok(completion)) => {
            if !completion.success {
                (
                    LoginStatus::Failed,
                    Some(
                        completion
                            .error
                            .unwrap_or_else(|| "Codex login was not completed.".to_string()),
                    ),
                    None,
                )
            } else {
                match read_account_email(&mut reader, &stdin).await {
                    Ok(Some(observed)) => (
                        LoginStatus::Succeeded,
                        Some(format!("Codex login completed for {}.", observed)),
                        Some(observed),
                    ),
                    Ok(None) => (
                        LoginStatus::Succeeded,
                        Some("Codex login completed.".to_string()),
                        None,
                    ),
                    Err(_) => (
                        LoginStatus::Succeeded,
                        Some("Codex login completed.".to_string()),
                        None,
                    ),
                }
            }
        }
        Ok(Err(_)) => (
            LoginStatus::Failed,
            Some("Codex login failed.".to_string()),
            None,
        ),
        Err(_) => (
            LoginStatus::Expired,
            Some("Login attempt expired.".to_string()),
            None,
        ),
    };

    {
        let mut records = records.write().await;
        if let Some(record) = records.get_mut(&key) {
            if record.attempt.status == LoginStatus::Pending {
                record.attempt.status = final_status;
                record.attempt.message = message;
                record.attempt.observed_email = observed_email;
            }
            record.session = None;
        }
    }

    let mut child = child.lock().await;
    let _ = child.kill().await;
}

struct LoginCompletion {
    success: bool,
    error: Option<String>,
}

async fn wait_for_completion(
    reader: &mut Lines<BufReader<ChildStdout>>,
    login_id: &Option<String>,
) -> Result<LoginCompletion, LoginError> {
    loop {
        let msg = read_message(reader).await?;
        if msg.get("method").and_then(|v| v.as_str()) == Some("account/login/completed") {
            let params = msg.get("params").cloned().unwrap_or(Value::Null);
            let message_login_id = params
                .get("loginId")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            if let Some(expected) = login_id {
                if let Some(got) = &message_login_id {
                    if got != expected {
                        continue;
                    }
                }
            }
            return Ok(LoginCompletion {
                success: params
                    .get("success")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false),
                error: params
                    .get("error")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
            });
        }
    }
}

async fn read_account_email(
    reader: &mut Lines<BufReader<ChildStdout>>,
    stdin: &Arc<Mutex<ChildStdin>>,
) -> Result<Option<String>, LoginError> {
    {
        let mut stdin = stdin.lock().await;
        write_message(
            &mut stdin,
            &json!({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "account/read",
                "params": {"refreshToken": true}
            }),
        )
        .await?;
    }
    let result = wait_for_response(reader, 3, Duration::from_secs(10)).await?;
    Ok(result
        .get("account")
        .and_then(|a| a.get("email"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string()))
}

async fn write_message(stdin: &mut ChildStdin, msg: &Value) -> Result<(), LoginError> {
    let mut line = serde_json::to_vec(msg).map_err(|e| LoginError::Internal(e.to_string()))?;
    line.push(b'\n');
    stdin
        .write_all(&line)
        .await
        .map_err(|e| LoginError::Internal(format!("failed to write to codex: {e}")))?;
    stdin
        .flush()
        .await
        .map_err(|e| LoginError::Internal(format!("failed to flush codex stdin: {e}")))?;
    Ok(())
}

async fn read_message(reader: &mut Lines<BufReader<ChildStdout>>) -> Result<Value, LoginError> {
    match reader.next_line().await {
        Ok(Some(line)) => serde_json::from_str::<Value>(&line)
            .map_err(|e| LoginError::Internal(format!("invalid JSON from codex: {e}"))),
        Ok(None) => Err(LoginError::Internal(
            "codex app-server closed stdout".to_string(),
        )),
        Err(e) => Err(LoginError::Internal(format!(
            "failed reading codex output: {e}"
        ))),
    }
}

async fn wait_for_response(
    reader: &mut Lines<BufReader<ChildStdout>>,
    id: i64,
    timeout_dur: Duration,
) -> Result<Value, LoginError> {
    let fut = async {
        loop {
            let msg = read_message(reader).await?;
            if msg.get("id") == Some(&json!(id)) {
                if let Some(err) = msg.get("error") {
                    return Err(LoginError::Internal(format!("codex error: {err}")));
                }
                return Ok(msg.get("result").cloned().unwrap_or(Value::Null));
            }
        }
    };
    match timeout(timeout_dur, fut).await {
        Ok(inner) => inner,
        Err(_) => Err(LoginError::Internal(
            "codex app-server timed out".to_string(),
        )),
    }
}
