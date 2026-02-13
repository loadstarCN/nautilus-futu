pub mod connection;
pub mod init;
pub mod keepalive;
pub mod dispatcher;

use std::sync::Arc;
use tokio::sync::mpsc;

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
    pub async fn init(&mut self) -> Result<&InitConnectResponse, init::InitError> {
        let resp = init::init_connect(&self.conn).await?;

        // Start keepalive
        let keepalive_handle = keepalive::start_keepalive(
            Arc::clone(&self.conn),
            resp.keep_alive_interval,
        );
        self.keepalive_handle = Some(keepalive_handle);

        // Start receive loop
        let conn = Arc::clone(&self.conn);
        let dispatcher = Arc::clone(&self.dispatcher);
        let recv_handle = tokio::spawn(async move {
            loop {
                match conn.recv().await {
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
        });
        self.recv_handle = Some(recv_handle);

        self.init_response = Some(resp);
        Ok(self.init_response.as_ref().unwrap())
    }

    /// Send a request and wait for the response.
    pub async fn request(&self, proto_id: u32, body: &[u8]) -> Result<FutuMessage, ConnectionError> {
        let serial_no = self.conn.send(proto_id, body).await?;
        let rx = self.dispatcher.register_request(serial_no).await;
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

    /// Disconnect and clean up.
    pub async fn disconnect(&mut self) {
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
