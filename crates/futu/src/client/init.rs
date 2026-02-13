use prost::Message;
use crate::client::connection::{FutuConnection, ConnectionError};

/// ProtoID for InitConnect
const PROTO_ID_INIT_CONNECT: u32 = 1001;

/// InitConnect response data
#[derive(Debug, Clone)]
pub struct InitConnectResponse {
    pub server_ver: i32,
    pub login_user_id: u64,
    pub conn_id: u64,
    pub conn_aes_key: String,
    pub keep_alive_interval: i32,
}

/// Perform the InitConnect handshake.
pub async fn init_connect(conn: &FutuConnection) -> Result<InitConnectResponse, InitError> {
    let c2s = crate::generated::init_connect::C2s {
        client_ver: conn.config().client_ver,
        client_id: conn.config().client_id.clone(),
        recv_notify: Some(true),
        // Encryption requires RSA keys configured in both FutuOpenD and client.
        // -1 = PacketEncAlgo_None, 0 = FTAES_ECB
        packet_enc_algo: Some(if conn.config().enable_encryption { 0 } else { -1 }),
        push_proto_fmt: Some(0), // Protobuf
        programming_language: Some("Rust".to_string()),
    };

    let request = crate::generated::init_connect::Request { c2s };

    let body = request.encode_to_vec();
    let _serial = conn.send(PROTO_ID_INIT_CONNECT, &body).await
        .map_err(InitError::Connection)?;

    // Receive response
    let msg = conn.recv().await.map_err(InitError::Connection)?;
    if msg.proto_id != PROTO_ID_INIT_CONNECT {
        return Err(InitError::UnexpectedProto(msg.proto_id));
    }

    let response = crate::generated::init_connect::Response::decode(msg.body.as_slice())
        .map_err(|e| InitError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(InitError::ServerError {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    let s2c = response.s2c.ok_or(InitError::MissingS2C)?;

    let result = InitConnectResponse {
        server_ver: s2c.server_ver,
        login_user_id: s2c.login_user_id,
        conn_id: s2c.conn_id,
        conn_aes_key: s2c.conn_aes_key.clone(),
        keep_alive_interval: s2c.keep_alive_interval,
    };

    // Only set up AES encryption if packet_enc_algo was requested (not -1/None).
    // Encryption requires RSA keys configured in FutuOpenD; without RSA keys,
    // the server never encrypts regardless of this setting.
    let key_bytes = result.conn_aes_key.as_bytes();
    if conn.config().enable_encryption && key_bytes.len() == 16 {
        let mut key = [0u8; 16];
        key.copy_from_slice(key_bytes);
        conn.set_cipher(&key).await;
        tracing::info!("AES-ECB encryption enabled");
    } else if conn.config().enable_encryption {
        tracing::warn!("Encryption requested but connAESKey is {} bytes (expected 16)", key_bytes.len());
    }

    // Store connection ID
    conn.set_conn_id(result.conn_id).await;

    tracing::info!(
        "InitConnect success: server_ver={}, conn_id={}, keepalive_interval={}s",
        result.server_ver, result.conn_id, result.keep_alive_interval
    );

    Ok(result)
}

#[derive(Debug, thiserror::Error)]
pub enum InitError {
    #[error("connection error: {0}")]
    Connection(#[from] ConnectionError),
    #[error("unexpected proto_id: {0}")]
    UnexpectedProto(u32),
    #[error("decode error: {0}")]
    Decode(String),
    #[error("server error (retType={ret_type}): {msg}")]
    ServerError { ret_type: i32, msg: String },
    #[error("missing S2C in response")]
    MissingS2C,
}
