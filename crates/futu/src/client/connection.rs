use std::sync::atomic::{AtomicU32, Ordering};
use tokio::net::TcpStream;
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};
use tokio::sync::Mutex;
use tokio_util::codec::{FramedRead, FramedWrite};
use futures::stream::StreamExt;
use futures::sink::SinkExt;

use crate::config::FutuConfig;
use crate::protocol::{FutuCodec, FutuMessage};
use crate::protocol::encryption::AesEcbCipher;

type Writer = FramedWrite<OwnedWriteHalf, FutuCodec>;
type Reader = FramedRead<OwnedReadHalf, FutuCodec>;

/// Manages the TCP connection to Futu OpenD.
/// Read and write halves are split to avoid deadlocks.
pub struct FutuConnection {
    config: FutuConfig,
    writer: Mutex<Writer>,
    reader: Mutex<Reader>,
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
        // Split TCP stream into independent read/write halves (no shared lock)
        let (read_half, write_half) = stream.into_split();
        let reader = FramedRead::new(read_half, FutuCodec);
        let writer = FramedWrite::new(write_half, FutuCodec);

        Ok(Self {
            config,
            writer: Mutex::new(writer),
            reader: Mutex::new(reader),
            serial_counter: AtomicU32::new(1),
            cipher: Mutex::new(None),
            conn_id: Mutex::new(0),
        })
    }

    /// Get the next serial number.
    pub fn next_serial(&self) -> u32 {
        self.serial_counter.fetch_add(1, Ordering::SeqCst)
    }

    /// Send a message (with optional encryption), auto-generating serial number.
    pub async fn send(&self, proto_id: u32, body: &[u8]) -> Result<u32, ConnectionError> {
        let serial_no = self.next_serial();
        self.send_with_serial(proto_id, body, serial_no).await?;
        Ok(serial_no)
    }

    /// Send a message with a specific serial number (with optional encryption).
    pub async fn send_with_serial(&self, proto_id: u32, body: &[u8], serial_no: u32) -> Result<(), ConnectionError> {
        let cipher = self.cipher.lock().await;
        let encrypted = cipher.is_some();
        let body_to_send = if let Some(ref aes) = *cipher {
            aes.encrypt(body)
        } else {
            body.to_vec()
        };
        drop(cipher);

        tracing::debug!("SEND proto_id={}, serial_no={}, body_len={}, encrypted={}", proto_id, serial_no, body_to_send.len(), encrypted);

        let msg = FutuMessage {
            proto_id,
            serial_no,
            body: body_to_send,
        };

        let mut writer = self.writer.lock().await;
        writer.send(msg).await.map_err(|e| ConnectionError::Send(e.to_string()))?;
        Ok(())
    }

    /// Receive the next message (with optional decryption).
    pub async fn recv(&self) -> Result<FutuMessage, ConnectionError> {
        let mut reader = self.reader.lock().await;
        match reader.next().await {
            Some(Ok(mut msg)) => {
                tracing::debug!("RECV proto_id={}, serial_no={}, body_len={}", msg.proto_id, msg.serial_no, msg.body.len());
                drop(reader); // Release reader lock before acquiring cipher lock
                let mut cipher = self.cipher.lock().await;
                if let Some(ref aes) = *cipher {
                    if !msg.body.is_empty() {
                        if msg.body.len() % 16 == 0 {
                            msg.body = aes.decrypt(&msg.body)
                                .map_err(|e| ConnectionError::Decryption(e.to_string()))?;
                        } else {
                            // Body length is not a multiple of 16 — server is NOT encrypting.
                            // This happens when FutuOpenD has no RSA keys configured.
                            // Disable encryption for all subsequent communication.
                            tracing::warn!("Server response not encrypted (body_len={}), disabling cipher", msg.body.len());
                            *cipher = None;
                        }
                    }
                }
                Ok(msg)
            }
            Some(Err(e)) => {
                tracing::error!("Receive error: {}", e);
                Err(ConnectionError::Receive(e.to_string()))
            }
            None => {
                tracing::warn!("Connection disconnected");
                Err(ConnectionError::Disconnected)
            }
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
