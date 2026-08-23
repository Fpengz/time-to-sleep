use serde_json::Value;
use tokio::sync::broadcast::{self, Receiver, Sender};

pub struct EventBroadcaster {
    sender: Sender<String>,
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

    pub fn subscribe(&self) -> Receiver<String> {
        self.sender.subscribe()
    }

    pub fn has_subscribers(&self) -> bool {
        self.sender.receiver_count() > 0
    }

    pub fn broadcast(&self, event_type: &str, data: &Value) {
        if !self.has_subscribers() {
            return;
        }
        let msg = format!("event: {}\ndata: {}\n\n", event_type, data);
        let _ = self.sender.send(msg);
    }
}
