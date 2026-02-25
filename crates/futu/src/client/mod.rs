pub mod connection;
pub mod init;
pub mod keepalive;
pub mod dispatcher;

use std::sync::Arc;
use tokio::sync::{mpsc, oneshot};

use crate::config::FutuConfig;
use crate::protocol::FutuMessage;
use connection::{FutuConnection, ConnectionError};
use init::InitConnectResponse;
use dispatcher::Dispatcher;

/// The main Futu client that manages connection, heartbeat, and message dispatch.
pub struct FutuClient {
    conn: Arc<FutuConnection>,
    dispatcher: Arc<Dispatcher>,
    keepalive_handle: Option<tokio::task::JoinHandle<()>>,
    recv_handle: Option<tokio::task::JoinHandle<()>>,
    init_response: Option<InitConnectResponse>,
}

impl FutuClient {
    /// Create a new FutuClient and connect to OpenD.
    pub async fn connect(config: FutuConfig) -> Result<Self, ConnectionError> {
        let conn = Arc::new(FutuConnection::connect(config).await?);
        let dispatcher = Arc::new(Dispatcher::new());

        Ok(Self {
            conn,
            dispatcher,
            keepalive_handle: None,
            recv_handle: None,
            init_response: None,
        })
    }

    /// Perform the InitConnect handshake and start keepalive + recv loops.
    /// Safe to call multiple times — returns the existing response if already initialized.
    pub async fn init(&mut self) -> Result<&InitConnectResponse, init::InitError> {
        if let Some(ref resp) = self.init_response {
            return Ok(resp);
        }

        let resp = init::init_connect(&self.conn).await?;
        tracing::info!("InitConnect success, keepalive_interval={}s", resp.keep_alive_interval);

        // Start keepalive with failure notification channel
        let (ka_fail_tx, ka_fail_rx) = oneshot::channel();
        let keepalive_handle = keepalive::start_keepalive(
            Arc::clone(&self.conn),
            resp.keep_alive_interval,
            ka_fail_tx,
        );
        self.keepalive_handle = Some(keepalive_handle);

        // Start receive loop — also monitors keepalive failure signal
        let conn = Arc::clone(&self.conn);
        let dispatcher = Arc::clone(&self.dispatcher);
        let recv_handle = tokio::spawn(async move {
            tracing::debug!("Recv loop started");
            let mut ka_fail_rx = ka_fail_rx;
            loop {
                tokio::select! {
                    result = conn.recv() => {
                        match result {
                            Ok(msg) => {
                                dispatcher.dispatch(msg).await;
                            }
                            Err(ConnectionError::Disconnected) => {
                                tracing::warn!("Connection disconnected");
                                break;
                            }
                            Err(e) => {
                                tracing::error!("Receive error: {}", e);
                                break;
                            }
                        }
                    }
                    _ = &mut ka_fail_rx => {
                        tracing::warn!("Keepalive failure detected, closing recv loop");
                        break;
                    }
                }
            }
            // Clear pending requests so callers don't hang forever
            dispatcher.clear_pending().await;
        });
        self.recv_handle = Some(recv_handle);

        self.init_response = Some(resp);
        // SAFETY: init_response was set to Some on the line above
        Ok(self.init_response.as_ref().expect("init_response was just set"))
    }

    /// Send a request and wait for the response.
    pub async fn request(&self, proto_id: u32, body: &[u8]) -> Result<FutuMessage, ConnectionError> {
        // Register BEFORE sending to avoid race with recv loop
        let serial_no = self.conn.next_serial();
        let rx = self.dispatcher.register_request(serial_no).await;
        self.conn.send_with_serial(proto_id, body, serial_no).await?;
        rx.await.map_err(|_| ConnectionError::Disconnected)
    }

    /// Send a message without waiting for response (fire-and-forget).
    pub async fn send(&self, proto_id: u32, body: &[u8]) -> Result<u32, ConnectionError> {
        self.conn.send(proto_id, body).await
    }

    /// Register a handler for push notifications of a specific proto_id.
    pub async fn subscribe_push(&self, proto_id: u32) -> mpsc::UnboundedReceiver<FutuMessage> {
        self.dispatcher.register_push(proto_id).await
    }

    /// Get the connection reference.
    pub fn connection(&self) -> &Arc<FutuConnection> {
        &self.conn
    }

    /// Get the init response.
    pub fn init_response(&self) -> Option<&InitConnectResponse> {
        self.init_response.as_ref()
    }

    /// Clear all pending requests so callers get `Disconnected` instead of hanging.
    pub async fn clear_pending(&self) {
        self.dispatcher.clear_pending().await;
    }

    /// Disconnect and clean up.
    pub async fn disconnect(&mut self) {
        // Clear pending requests first so callers get Disconnected error
        self.dispatcher.clear_pending().await;
        if let Some(handle) = self.keepalive_handle.take() {
            handle.abort();
        }
        if let Some(handle) = self.recv_handle.take() {
            handle.abort();
        }
        tracing::info!("Disconnected from Futu OpenD");
    }
}

impl Drop for FutuClient {
    fn drop(&mut self) {
        if let Some(handle) = self.keepalive_handle.take() {
            handle.abort();
        }
        if let Some(handle) = self.recv_handle.take() {
            handle.abort();
        }
    }
}
