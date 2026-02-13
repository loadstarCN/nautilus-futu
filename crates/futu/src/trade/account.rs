use prost::Message;
use crate::client::FutuClient;
use crate::client::connection::ConnectionError;

const PROTO_TRD_GET_ACC_LIST: u32 = 2001;
const PROTO_TRD_UNLOCK_TRADE: u32 = 2005;

#[derive(Debug, thiserror::Error)]
pub enum TradeError {
    #[error("connection error: {0}")]
    Connection(#[from] ConnectionError),
    #[error("decode error: {0}")]
    Decode(String),
    #[error("server error (retType={ret_type}): {msg}")]
    Server { ret_type: i32, msg: String },
}

/// Get the list of trading accounts.
pub async fn get_acc_list(
    client: &FutuClient,
    user_id: u64,
) -> Result<crate::generated::trd_get_acc_list::Response, TradeError> {
    let c2s = crate::generated::trd_get_acc_list::C2s {
        user_id,
        ..Default::default()
    };
    let request = crate::generated::trd_get_acc_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_ACC_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_acc_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Unlock trading (required before placing orders in real environment).
pub async fn unlock_trade(
    client: &FutuClient,
    unlock: bool,
    pwd_md5: String,
    security_firm: Option<i32>,
) -> Result<(), TradeError> {
    let c2s = crate::generated::trd_unlock_trade::C2s {
        unlock,
        pwd_md5: Some(pwd_md5),
        security_firm,
    };
    let request = crate::generated::trd_unlock_trade::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_UNLOCK_TRADE, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_unlock_trade::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(())
}
