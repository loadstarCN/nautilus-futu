use prost::Message;
use crate::client::connection::{FutuConnection, ConnectionError};
use crate::protocol::encryption::RsaCipher;

/// ProtoID for InitConnect
const PROTO_ID_INIT_CONNECT: u32 = 1001;

/// `Common.PacketEncAlgo` values.
const PACKET_ENC_ALGO_FTAES_ECB: i32 = 0;
const PACKET_ENC_ALGO_NONE: i32 = -1;

/// InitConnect response data
#[derive(Debug, Clone)]
pub struct InitConnectResponse {
    pub server_ver: i32,
    pub login_user_id: u64,
    pub conn_id: u64,
    pub conn_aes_key: String,
    pub keep_alive_interval: i32,
    /// Whether AES encryption was negotiated for this connection.
    pub encrypted: bool,
}

/// Load the RSA cipher if the config points at a private key file.
fn load_rsa(conn: &FutuConnection) -> Result<Option<RsaCipher>, InitError> {
    let config = conn.config();
    match &config.rsa_key_path {
        Some(path) => {
            let cipher = RsaCipher::from_pem_file(path)
                .map_err(|e| InitError::Encryption(e.to_string()))?;
            tracing::info!("Loaded RSA key ({} bytes) from {}", cipher.key_size(), path.display());
            Ok(Some(cipher))
        }
        None => {
            if config.enable_encryption {
                tracing::warn!("enable_encryption=true but no rsa_key_path configured; connecting in plaintext");
            }
            Ok(None)
        }
    }
}

/// Perform the InitConnect handshake.
///
/// When an RSA private key is configured the request body is RSA-encrypted,
/// the response body is RSA-decrypted, and the returned `connAESKey` is
/// installed as the AES-ECB cipher for every subsequent packet.  This is the
/// same scheme the official `futu-api` client uses.
pub async fn init_connect(conn: &FutuConnection) -> Result<InitConnectResponse, InitError> {
    let rsa = load_rsa(conn)?;
    let want_encryption = rsa.is_some();

    let c2s = crate::generated::init_connect::C2s {
        client_ver: conn.config().client_ver,
        client_id: conn.config().client_id.clone(),
        recv_notify: Some(true),
        packet_enc_algo: Some(if want_encryption { PACKET_ENC_ALGO_FTAES_ECB } else { PACKET_ENC_ALGO_NONE }),
        push_proto_fmt: Some(0), // Protobuf
        programming_language: Some("Rust".to_string()),
    };

    let request = crate::generated::init_connect::Request { c2s };
    let body = request.encode_to_vec();

    let serial_no = conn.next_serial();
    match &rsa {
        Some(cipher) => {
            let encrypted = cipher.encrypt(&body).map_err(|e| InitError::Encryption(e.to_string()))?;
            conn.send_raw(PROTO_ID_INIT_CONNECT, encrypted, serial_no, true).await
                .map_err(InitError::Connection)?;
        }
        None => {
            conn.send_raw(PROTO_ID_INIT_CONNECT, body, serial_no, false).await
                .map_err(InitError::Connection)?;
        }
    }

    // Receive response (the AES cipher is not installed yet, so this is the raw body)
    let msg = conn.recv().await.map_err(InitError::Connection)?;
    if msg.proto_id != PROTO_ID_INIT_CONNECT {
        return Err(InitError::UnexpectedProto(msg.proto_id));
    }

    // `rsa_ok` records whether OpenD actually took part in the RSA handshake.
    // Only then will it AES-encrypt the rest of the session, so AES must not
    // be enabled after a plaintext fallback (OpenD without RSA configured).
    let mut rsa_ok = false;
    let body = match &rsa {
        Some(cipher) => match cipher.decrypt(&msg.body) {
            Ok(plain) => {
                rsa_ok = true;
                plain
            }
            Err(e) => {
                // OpenD without RSA configured answers in plaintext; fall back
                // gracefully rather than failing the whole connection.
                tracing::warn!("InitConnect response is not RSA-encrypted ({e}); falling back to plaintext");
                msg.body.clone()
            }
        },
        None => msg.body.clone(),
    };

    let response = crate::generated::init_connect::Response::decode(body.as_slice())
        .map_err(|e| InitError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(InitError::ServerError {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    let s2c = response.s2c.ok_or(InitError::MissingS2C)?;

    let mut result = InitConnectResponse {
        server_ver: s2c.server_ver,
        login_user_id: s2c.login_user_id,
        conn_id: s2c.conn_id,
        conn_aes_key: s2c.conn_aes_key.clone(),
        keep_alive_interval: s2c.keep_alive_interval,
        encrypted: false,
    };

    // Install AES only when the RSA handshake really happened and OpenD
    // handed us a 16-byte key.
    let key_bytes = result.conn_aes_key.as_bytes();
    if rsa_ok && key_bytes.len() == 16 {
        let mut key = [0u8; 16];
        key.copy_from_slice(key_bytes);
        conn.set_cipher(&key).await;
        result.encrypted = true;
        tracing::info!("AES-ECB encryption enabled");
    } else if rsa_ok {
        tracing::warn!("Encryption requested but connAESKey is {} bytes (expected 16); continuing in plaintext", key_bytes.len());
    } else if want_encryption {
        tracing::warn!("RSA key configured but OpenD did not encrypt the handshake; session stays in plaintext");
    }

    // Store connection ID
    conn.set_conn_id(result.conn_id).await;

    tracing::info!(
        "InitConnect success: server_ver={}, conn_id={}, keepalive_interval={}s, encrypted={}",
        result.server_ver, result.conn_id, result.keep_alive_interval, result.encrypted
    );

    Ok(result)
}

/// ProtoID for GetGlobalState
const PROTO_ID_GET_GLOBAL_STATE: u32 = 1002;

/// Query global state from Futu OpenD.
pub async fn get_global_state(
    client: &crate::client::FutuClient,
    user_id: u64,
) -> Result<crate::generated::get_global_state::Response, InitError> {
    let c2s = crate::generated::get_global_state::C2s { user_id };
    let request = crate::generated::get_global_state::Request { c2s };
    let body = request.encode_to_vec();

    let msg = client.request(PROTO_ID_GET_GLOBAL_STATE, &body).await
        .map_err(InitError::Connection)?;

    let response = crate::generated::get_global_state::Response::decode(msg.body.as_slice())
        .map_err(|e| InitError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(InitError::ServerError {
            ret_type: response.ret_type,
            msg: response.ret_msg.clone().unwrap_or_default(),
        });
    }

    Ok(response)
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
    #[error("encryption error: {0}")]
    Encryption(String),
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constant() {
        assert_eq!(PROTO_ID_INIT_CONNECT, 1001);
        assert_eq!(PACKET_ENC_ALGO_FTAES_ECB, 0);
        assert_eq!(PACKET_ENC_ALGO_NONE, -1);
    }

    #[test]
    fn test_init_connect_request_encode_decode() {
        let c2s = crate::generated::init_connect::C2s {
            client_ver: 100,
            client_id: "test_client".to_string(),
            recv_notify: Some(true),
            packet_enc_algo: Some(-1),
            push_proto_fmt: Some(0),
            programming_language: Some("Rust".to_string()),
        };
        let request = crate::generated::init_connect::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::init_connect::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.client_ver, 100);
        assert_eq!(decoded.c2s.client_id, "test_client");
        assert_eq!(decoded.c2s.recv_notify, Some(true));
        assert_eq!(decoded.c2s.packet_enc_algo, Some(-1));
        assert_eq!(decoded.c2s.programming_language, Some("Rust".to_string()));
    }

    #[test]
    fn test_init_connect_response_success() {
        let s2c = crate::generated::init_connect::S2c {
            server_ver: 500,
            login_user_id: 12345,
            conn_id: 99,
            conn_aes_key: "0123456789abcdef".to_string(),
            keep_alive_interval: 10,
            aes_cb_civ: None,
            user_attribution: None,
        };
        let response = crate::generated::init_connect::Response {
            ret_type: 0,
            ret_msg: Some("success".to_string()),
            err_code: None,
            s2c: Some(s2c),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::init_connect::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.server_ver, 500);
        assert_eq!(s2c.login_user_id, 12345);
        assert_eq!(s2c.conn_id, 99);
        assert_eq!(s2c.conn_aes_key, "0123456789abcdef");
        assert_eq!(s2c.keep_alive_interval, 10);
    }

    #[test]
    fn test_init_connect_response_error() {
        let response = crate::generated::init_connect::Response {
            ret_type: -1,
            ret_msg: Some("invalid client".to_string()),
            err_code: Some(1001),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::init_connect::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg, Some("invalid client".to_string()));
        assert_eq!(decoded.err_code, Some(1001));
        assert!(decoded.s2c.is_none());
    }

    #[test]
    fn test_get_global_state_proto_id() {
        assert_eq!(PROTO_ID_GET_GLOBAL_STATE, 1002);
    }

    #[test]
    fn test_get_global_state_request_encode_decode() {
        let c2s = crate::generated::get_global_state::C2s { user_id: 12345 };
        let request = crate::generated::get_global_state::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::get_global_state::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.user_id, 12345);
    }

    #[test]
    fn test_get_global_state_response_success() {
        let s2c = crate::generated::get_global_state::S2c {
            market_hk: 5,       // MarketState_Rest
            market_us: 5,
            market_sh: 5,
            market_sz: 5,
            market_hk_future: 5,
            qot_logined: true,
            trd_logined: true,
            server_ver: 500,
            server_build_no: 1234,
            time: 1704067200,
            local_time: Some(1704067200.123),
            market_us_future: Some(5),
            market_sg_future: Some(5),
            market_jp_future: Some(5),
        };
        let response = crate::generated::get_global_state::Response {
            ret_type: 0,
            ret_msg: Some("success".to_string()),
            err_code: None,
            s2c: Some(s2c),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::get_global_state::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.market_hk, 5);
        assert!(s2c.qot_logined);
        assert_eq!(s2c.server_ver, 500);
        assert_eq!(s2c.time, 1704067200);
    }

    #[test]
    fn test_get_global_state_response_error() {
        let response = crate::generated::get_global_state::Response {
            ret_type: -1,
            ret_msg: Some("not connected".to_string()),
            err_code: Some(2001),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::get_global_state::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert!(decoded.s2c.is_none());
    }
}
