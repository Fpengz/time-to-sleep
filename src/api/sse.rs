use serde_json::Value;
use tokio::sync::broadcast::{self, Receiver, Sender};

#[derive(Debug, Clone)]
pub struct BroadcastEvent {
    pub event_type: String,
    pub data: String,
}

pub struct EventBroadcaster {
    sender: Sender<BroadcastEvent>,
}

impl Default for EventBroadcaster {
    fn default() -> Self {
        Self::new()
    }
}

impl EventBroadcaster {
    pub fn new() -> Self {
        let (sender, _) = broadcast::channel(100);
        Self { sender }
    }

    pub fn subscribe(&self) -> Receiver<BroadcastEvent> {
        self.sender.subscribe()
    }

    pub fn has_subscribers(&self) -> bool {
        self.sender.receiver_count() > 0
    }

    pub fn broadcast(&self, event_type: &str, data: &Value) {
        if !self.has_subscribers() {
            return;
        }
        let _ = self.sender.send(BroadcastEvent {
            event_type: event_type.to_owned(),
            data: data.to_string(),
        });
    }
}
