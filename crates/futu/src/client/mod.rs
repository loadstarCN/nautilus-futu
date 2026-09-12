pub mod connection;
pub mod init;
pub mod keepalive;
pub mod dispatcher;

use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot, watch};

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
    /// `true` from a successful `init()` until the recv loop exits for any
    /// reason (peer closed, IO error, keepalive failure) or `disconnect()`.
    connected_tx: watch::Sender<bool>,
    request_timeout: Duration,
}

impl FutuClient {
    /// Create a new FutuClient and connect to OpenD.
    pub async fn connect(config: FutuConfig) -> Result<Self, ConnectionError> {
        let request_timeout = Duration::from_secs(config.request_timeout_secs.max(1));
        let conn = Arc::new(FutuConnection::connect(config).await?);
        let dispatcher = Arc::new(Dispatcher::new());
        let (connected_tx, _rx) = watch::channel(false);

        Ok(Self {
            conn,
            dispatcher,
            keepalive_handle: None,
            recv_handle: None,
            init_response: None,
            connected_tx,
            request_timeout,
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
        let connected_tx = self.connected_tx.clone();
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
            // Flip the connection flag first so anyone polling sees the change,
            // then release everything waiting on this connection.
            connected_tx.send_replace(false);
            dispatcher.clear_pending().await;
            dispatcher.clear_push_handlers().await;
        });
        self.recv_handle = Some(recv_handle);

        self.connected_tx.send_replace(true);
        self.init_response = Some(resp);
        // SAFETY: init_response was set to Some on the line above
        Ok(self.init_response.as_ref().expect("init_response was just set"))
    }

    /// Whether the connection is currently alive (initialized and recv loop running).
    pub fn is_connected(&self) -> bool {
        *self.connected_tx.borrow()
    }

    /// A watch receiver that flips to `false` when the connection dies.
    /// Use `rx.wait_for(|c| !*c)` to await disconnection without polling.
    pub fn connected_watch(&self) -> watch::Receiver<bool> {
        self.connected_tx.subscribe()
    }

    /// Send a request and wait for the response (bounded by the configured request timeout).
    pub async fn request(&self, proto_id: u32, body: &[u8]) -> Result<FutuMessage, ConnectionError> {
        if !self.is_connected() {
            return Err(ConnectionError::Disconnected);
        }
        // Register BEFORE sending to avoid race with recv loop
        let serial_no = self.conn.next_serial();
        let rx = self.dispatcher.register_request(serial_no).await;
        if let Err(e) = self.conn.send_with_serial(proto_id, body, serial_no).await {
            self.dispatcher.remove_pending(serial_no).await;
            return Err(e);
        }
        match tokio::time::timeout(self.request_timeout, rx).await {
            Ok(Ok(msg)) => Ok(msg),
            Ok(Err(_)) => Err(ConnectionError::Disconnected),
            Err(_) => {
                self.dispatcher.remove_pending(serial_no).await;
                tracing::warn!("Request proto_id={} serial_no={} timed out after {:?}", proto_id, serial_no, self.request_timeout);
                Err(ConnectionError::Timeout(self.request_timeout.as_secs(), proto_id))
            }
        }
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
        self.connected_tx.send_replace(false);
        // Clear pending requests first so callers get Disconnected error
        self.dispatcher.clear_pending().await;
        self.dispatcher.clear_push_handlers().await;
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
        self.connected_tx.send_replace(false);
        if let Some(handle) = self.keepalive_handle.take() {
            handle.abort();
        }
        if let Some(handle) = self.recv_handle.take() {
            handle.abort();
        }
    }
}

/// End-to-end tests against an in-process fake OpenD (a plain tokio TCP
/// server speaking the Futu framing protocol).
#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{FutuCodec, FutuMessage};
    use futures::{SinkExt, StreamExt};
    use prost::Message;
    use tokio::net::TcpListener;
    use tokio_util::codec::Framed;

    /// Behaviour knobs for the fake server.
    #[derive(Clone, Default)]
    struct FakeOpts {
        /// Ignore requests with this proto_id (never reply) to exercise timeouts.
        ignore_proto: Option<u32>,
        /// Close the socket right after replying to InitConnect.
        close_after_init: bool,
        /// Push a Qot_UpdateBasicQot (3005) after the first Qot_Sub (3001).
        push_after_sub: bool,
    }

    fn init_response_body() -> Vec<u8> {
        let s2c = crate::generated::init_connect::S2c {
            server_ver: 900,
            login_user_id: 42,
            conn_id: 7,
            conn_aes_key: String::new(),
            keep_alive_interval: 1,
            aes_cb_civ: None,
            user_attribution: None,
        };
        crate::generated::init_connect::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        }
        .encode_to_vec()
    }

    fn ok_sub_body() -> Vec<u8> {
        crate::generated::qot_sub::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::qot_sub::S2c {}),
        }
        .encode_to_vec()
    }

    fn push_body() -> Vec<u8> {
        let qot = crate::generated::qot_common::BasicQot {
            security: crate::generated::qot_common::Security { market: 1, code: "00700".into() },
            cur_price: 345.6,
            ..Default::default()
        };
        crate::generated::qot_update_basic_qot::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::qot_update_basic_qot::S2c { basic_qot_list: vec![qot] }),
        }
        .encode_to_vec()
    }

    /// Spawn the fake server; returns the bound address.
    async fn spawn_fake_opend(opts: FakeOpts) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                let opts = opts.clone();
                tokio::spawn(async move {
                    let mut framed = Framed::new(stream, FutuCodec);
                    while let Some(Ok(msg)) = framed.next().await {
                        if Some(msg.proto_id) == opts.ignore_proto {
                            continue;
                        }
                        let reply_body = match msg.proto_id {
                            1001 => init_response_body(),
                            1004 => crate::generated::keep_alive::Response {
                                ret_type: 0,
                                ret_msg: None,
                                err_code: None,
                                s2c: Some(crate::generated::keep_alive::S2c { time: 1 }),
                            }
                            .encode_to_vec(),
                            3001 => ok_sub_body(),
                            _ => vec![],
                        };
                        let reply = FutuMessage { proto_id: msg.proto_id, serial_no: msg.serial_no, body: reply_body };
                        if framed.send(reply).await.is_err() {
                            break;
                        }
                        if msg.proto_id == 1001 && opts.close_after_init {
                            break;
                        }
                        if msg.proto_id == 3001 && opts.push_after_sub {
                            let push = FutuMessage { proto_id: 3005, serial_no: 0, body: push_body() };
                            let _ = framed.send(push).await;
                        }
                    }
                });
            }
        });
        addr
    }

    async fn connect_client(addr: std::net::SocketAddr, timeout_secs: u64) -> FutuClient {
        let config = FutuConfig {
            host: addr.ip().to_string(),
            port: addr.port(),
            request_timeout_secs: timeout_secs,
            ..Default::default()
        };
        let mut client = FutuClient::connect(config).await.expect("tcp connect");
        client.init().await.expect("init");
        client
    }

    #[tokio::test]
    async fn test_handshake_and_request_roundtrip() {
        let addr = spawn_fake_opend(FakeOpts::default()).await;
        let client = connect_client(addr, 5).await;
        assert!(client.is_connected());
        let init = client.init_response().unwrap();
        assert_eq!(init.login_user_id, 42);
        assert_eq!(init.conn_id, 7);

        let body = crate::generated::qot_sub::Request {
            c2s: crate::generated::qot_sub::C2s {
                security_list: vec![],
                sub_type_list: vec![],
                is_sub_or_un_sub: true,
                ..Default::default()
            },
        }
        .encode_to_vec();
        let resp = client.request(3001, &body).await.expect("request");
        assert_eq!(resp.proto_id, 3001);
        let decoded = crate::generated::qot_sub::Response::decode(resp.body.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
    }

    #[tokio::test]
    async fn test_request_timeout_clears_pending() {
        let addr = spawn_fake_opend(FakeOpts { ignore_proto: Some(3001), ..Default::default() }).await;
        let client = connect_client(addr, 1).await;
        let started = std::time::Instant::now();
        let err = client.request(3001, b"").await.unwrap_err();
        assert!(matches!(err, ConnectionError::Timeout(1, 3001)), "got {err:?}");
        assert!(started.elapsed() < Duration::from_secs(3));
        assert_eq!(client.dispatcher.pending_count().await, 0);
        // Connection itself is still healthy
        assert!(client.is_connected());
    }

    #[tokio::test]
    async fn test_peer_close_flips_connected_flag() {
        let addr = spawn_fake_opend(FakeOpts { close_after_init: true, ..Default::default() }).await;
        let client = connect_client(addr, 2).await;
        let mut watch_rx = client.connected_watch();
        tokio::time::timeout(Duration::from_secs(3), watch_rx.wait_for(|c| !*c))
            .await
            .expect("disconnect detected within 3s")
            .expect("watch alive");
        assert!(!client.is_connected());
        // Requests now fail fast instead of hanging
        assert!(matches!(client.request(3001, b"").await, Err(ConnectionError::Disconnected)));
    }

    #[tokio::test]
    async fn test_push_delivery_and_close_on_disconnect() {
        let addr = spawn_fake_opend(FakeOpts { push_after_sub: true, ..Default::default() }).await;
        let mut client = connect_client(addr, 5).await;
        let mut push_rx = client.subscribe_push(3005).await;
        client.request(3001, &[]).await.expect("sub");
        let push = tokio::time::timeout(Duration::from_secs(3), push_rx.recv())
            .await
            .expect("push within 3s")
            .expect("push message");
        assert_eq!(push.proto_id, 3005);
        let decoded = crate::generated::qot_update_basic_qot::Response::decode(push.body.as_slice()).unwrap();
        assert_eq!(decoded.s2c.unwrap().basic_qot_list[0].security.code, "00700");

        // Explicit disconnect closes push receivers so pollers observe end-of-stream
        client.disconnect().await;
        assert!(!client.is_connected());
        assert!(push_rx.recv().await.is_none());
    }
}
