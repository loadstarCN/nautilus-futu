use std::sync::atomic::{AtomicU32, Ordering};
use tokio::net::TcpStream;
use tokio::sync::Mutex;
use tokio_util::codec::Framed;
use futures::stream::StreamExt;
use futures::sink::SinkExt;

use crate::config::FutuConfig;
use crate::protocol::{FutuCodec, FutuMessage};
use crate::protocol::encryption::AesEcbCipher;

/// Manages the TCP connection to Futu OpenD.
pub struct FutuConnection {
    config: FutuConfig,
    framed: Mutex<Framed<TcpStream, FutuCodec>>,
    serial_counter: AtomicU32,
    cipher: Mutex<Option<AesEcbCipher>>,
    conn_id: Mutex<u64>,
}

impl FutuConnection {
    /// Connect to Futu OpenD gateway.
    pub async fn connect(config: FutuConfig) -> Result<Self, ConnectionError> {
        let addr = format!("{}:{}", config.host, config.port);
        tracing::info!("Connecting to Futu OpenD at {}", addr);
        let stream = TcpStream::connect(&addr).await?;
        stream.set_nodelay(true)?;
        let framed = Framed::new(stream, FutuCodec);

        Ok(Self {
            config,
            framed: Mutex::new(framed),
            serial_counter: AtomicU32::new(1),
            cipher: Mutex::new(None),
            conn_id: Mutex::new(0),
        })
    }

    /// Get the next serial number.
    pub fn next_serial(&self) -> u32 {
        self.serial_counter.fetch_add(1, Ordering::SeqCst)
    }

    /// Send a message (with optional encryption).
    pub async fn send(&self, proto_id: u32, body: &[u8]) -> Result<u32, ConnectionError> {
        let serial_no = self.next_serial();
        let cipher = self.cipher.lock().await;
        let body_to_send = if let Some(ref aes) = *cipher {
            aes.encrypt(body)
        } else {
            body.to_vec()
        };

        let msg = FutuMessage {
            proto_id,
            serial_no,
            body: body_to_send,
        };

        let mut framed = self.framed.lock().await;
        framed.send(msg).await.map_err(|e| ConnectionError::Send(e.to_string()))?;
        Ok(serial_no)
    }

    /// Receive the next message (with optional decryption).
    pub async fn recv(&self) -> Result<FutuMessage, ConnectionError> {
        let mut framed = self.framed.lock().await;
        match framed.next().await {
            Some(Ok(mut msg)) => {
                let cipher = self.cipher.lock().await;
                if let Some(ref aes) = *cipher {
                    if !msg.body.is_empty() {
                        msg.body = aes.decrypt(&msg.body)
                            .map_err(|e| ConnectionError::Decryption(e.to_string()))?;
                    }
                }
                Ok(msg)
            }
            Some(Err(e)) => Err(ConnectionError::Receive(e.to_string())),
            None => Err(ConnectionError::Disconnected),
        }
    }

    /// Set the AES encryption key (after InitConnect).
    pub async fn set_cipher(&self, key: &[u8; 16]) {
        let mut cipher = self.cipher.lock().await;
        *cipher = Some(AesEcbCipher::new(key));
    }

    /// Set the connection ID.
    pub async fn set_conn_id(&self, id: u64) {
        let mut conn_id = self.conn_id.lock().await;
        *conn_id = id;
    }

    /// Get the connection ID.
    pub async fn conn_id(&self) -> u64 {
        *self.conn_id.lock().await
    }

    pub fn config(&self) -> &FutuConfig {
        &self.config
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConnectionError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("send error: {0}")]
    Send(String),
    #[error("receive error: {0}")]
    Receive(String),
    #[error("decryption error: {0}")]
    Decryption(String),
    #[error("connection disconnected")]
    Disconnected,
}
