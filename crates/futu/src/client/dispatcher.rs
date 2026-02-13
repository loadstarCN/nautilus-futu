use std::collections::HashMap;
use tokio::sync::{mpsc, oneshot, Mutex};
use crate::protocol::FutuMessage;

/// Dispatches incoming messages to the appropriate handler.
/// - Request/response messages are matched by serial number.
/// - Push messages are dispatched by proto_id.
pub struct Dispatcher {
    /// Pending request-response pairs, keyed by serial number.
    pending: Mutex<HashMap<u32, oneshot::Sender<FutuMessage>>>,
    /// Push notification handlers, keyed by proto_id.
    push_handlers: Mutex<HashMap<u32, Vec<mpsc::UnboundedSender<FutuMessage>>>>,
}

impl Dispatcher {
    pub fn new() -> Self {
        Self {
            pending: Mutex::new(HashMap::new()),
            push_handlers: Mutex::new(HashMap::new()),
        }
    }

    /// Register a pending request. Returns a receiver for the response.
    pub async fn register_request(&self, serial_no: u32) -> oneshot::Receiver<FutuMessage> {
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(serial_no, tx);
        rx
    }

    /// Register a push handler for a specific proto_id.
    /// Returns a receiver that will receive push messages.
    pub async fn register_push(&self, proto_id: u32) -> mpsc::UnboundedReceiver<FutuMessage> {
        let (tx, rx) = mpsc::unbounded_channel();
        self.push_handlers.lock().await
            .entry(proto_id)
            .or_default()
            .push(tx);
        rx
    }

    /// Dispatch an incoming message.
    pub async fn dispatch(&self, msg: FutuMessage) {
        // First try to match as a response to a pending request
        let mut pending = self.pending.lock().await;
        if let Some(tx) = pending.remove(&msg.serial_no) {
            let _ = tx.send(msg);
            return;
        }
        drop(pending);

        // Otherwise treat as a push notification
        let handlers = self.push_handlers.lock().await;
        if let Some(senders) = handlers.get(&msg.proto_id) {
            for sender in senders {
                let _ = sender.send(msg.clone());
            }
        } else {
            tracing::debug!("No handler for proto_id={}, serial_no={}", msg.proto_id, msg.serial_no);
        }
    }
}
