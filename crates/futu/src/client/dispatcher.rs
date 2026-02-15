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

impl Default for Dispatcher {
    fn default() -> Self {
        Self::new()
    }
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
        let mut handlers = self.push_handlers.lock().await;
        if let Some(senders) = handlers.get_mut(&msg.proto_id) {
            // Remove closed channels, then send to remaining
            senders.retain(|s| !s.is_closed());
            for sender in senders.iter() {
                let _ = sender.send(msg.clone());
            }
        } else {
            tracing::debug!("No handler for proto_id={}, serial_no={}", msg.proto_id, msg.serial_no);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_msg(proto_id: u32, serial_no: u32, body: &[u8]) -> FutuMessage {
        FutuMessage {
            proto_id,
            serial_no,
            body: body.to_vec(),
        }
    }

    #[tokio::test]
    async fn test_request_response_dispatch() {
        let dispatcher = Dispatcher::new();
        let rx = dispatcher.register_request(100).await;
        let msg = make_msg(1001, 100, b"response");
        dispatcher.dispatch(msg).await;
        let received = rx.await.unwrap();
        assert_eq!(received.serial_no, 100);
        assert_eq!(received.body, b"response");
    }

    #[tokio::test]
    async fn test_request_unmatched() {
        let dispatcher = Dispatcher::new();
        // Dispatch a message with no registered handler — should not panic
        let msg = make_msg(1001, 999, b"orphan");
        dispatcher.dispatch(msg).await;
    }

    #[tokio::test]
    async fn test_push_dispatch() {
        let dispatcher = Dispatcher::new();
        let mut rx = dispatcher.register_push(3001).await;
        let msg = make_msg(3001, 0, b"push data");
        dispatcher.dispatch(msg).await;
        let received = rx.recv().await.unwrap();
        assert_eq!(received.proto_id, 3001);
        assert_eq!(received.body, b"push data");
    }

    #[tokio::test]
    async fn test_push_multiple_listeners() {
        let dispatcher = Dispatcher::new();
        let mut rx1 = dispatcher.register_push(3001).await;
        let mut rx2 = dispatcher.register_push(3001).await;
        let msg = make_msg(3001, 0, b"broadcast");
        dispatcher.dispatch(msg).await;
        let r1 = rx1.recv().await.unwrap();
        let r2 = rx2.recv().await.unwrap();
        assert_eq!(r1.body, b"broadcast");
        assert_eq!(r2.body, b"broadcast");
    }

    #[tokio::test]
    async fn test_serial_no_priority_over_proto_id() {
        let dispatcher = Dispatcher::new();
        // Register both a request handler (serial_no=50) and a push handler (proto_id=3001)
        let rx_req = dispatcher.register_request(50).await;
        let mut rx_push = dispatcher.register_push(3001).await;
        // Message matches both serial_no=50 and proto_id=3001 → request path wins
        let msg = make_msg(3001, 50, b"priority");
        dispatcher.dispatch(msg).await;
        let received = rx_req.await.unwrap();
        assert_eq!(received.body, b"priority");
        // Push handler should NOT have received anything
        assert!(rx_push.try_recv().is_err());
    }

    #[tokio::test]
    async fn test_request_oneshot_consumed() {
        let dispatcher = Dispatcher::new();
        let rx = dispatcher.register_request(77).await;
        // First dispatch — consumed by the oneshot
        dispatcher.dispatch(make_msg(1001, 77, b"first")).await;
        let received = rx.await.unwrap();
        assert_eq!(received.body, b"first");
        // Second dispatch with same serial_no — no handler, should not panic
        dispatcher.dispatch(make_msg(1001, 77, b"second")).await;
    }
}
