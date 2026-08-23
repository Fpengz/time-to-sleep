pub mod antigravity;
pub mod claude;
pub mod codex;
pub mod parsers;

use async_trait::async_trait;
use crate::domain::{AccountConfig, UsageSnapshot};

#[async_trait]
pub trait UsageProvider: Send + Sync {
    async fn fetch(&self, account: &AccountConfig) -> UsageSnapshot;
}
