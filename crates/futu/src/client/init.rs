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
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constant() {
        assert_eq!(PROTO_ID_INIT_CONNECT, 1001);
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
            market_cn: 5,
            market_hk_future: Some(5),
            market_us_future: Some(5),
            market_sg: Some(5),
            market_jp: Some(5),
            qot_logined: true,
            trd_logined: true,
            server_ver: Some(500),
            server_build_no: Some(1234),
            time: Some(1704067200),
            local_time: Some(1704067200.123),
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
        assert_eq!(s2c.market_us, 5);
        assert_eq!(s2c.market_cn, 5);
        assert!(s2c.qot_logined);
        assert!(s2c.trd_logined);
        assert_eq!(s2c.server_ver, Some(500));
        assert_eq!(s2c.time, Some(1704067200));
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

    #[test]
    fn test_get_global_state_roundtrip() {
        // Full encode → decode roundtrip for all fields
        let s2c = crate::generated::get_global_state::S2c {
            market_hk: 3,
            market_us: 6,
            market_cn: 1,
            market_hk_future: None,
            market_us_future: None,
            market_sg: Some(2),
            market_jp: None,
            qot_logined: false,
            trd_logined: true,
            server_ver: Some(321),
            server_build_no: None,
            time: Some(9999999),
            local_time: None,
        };
        let response = crate::generated::get_global_state::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::get_global_state::Response::decode(encoded.as_slice()).unwrap();
        let s = decoded.s2c.unwrap();
        assert_eq!(s.market_hk, 3);
        assert_eq!(s.market_us, 6);
        assert_eq!(s.market_cn, 1);
        assert_eq!(s.market_hk_future, None);
        assert_eq!(s.market_sg, Some(2));
        assert!(!s.qot_logined);
        assert!(s.trd_logined);
    }
}
