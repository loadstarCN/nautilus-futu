use prost::Message;
use crate::client::FutuClient;
use crate::client::connection::ConnectionError;

const PROTO_QOT_SUB: u32 = 3001;
const PROTO_QOT_REG_PUSH: u32 = 3002;

/// Subscribe to quote data for given securities.
pub async fn subscribe(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
    sub_types: Vec<i32>,
    is_sub: bool,
) -> Result<(), QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_sub::C2s {
        security_list,
        sub_type_list: sub_types,
        is_sub_or_un_sub: is_sub,
        is_reg_or_un_reg_push: Some(true),
        ..Default::default()
    };

    let request = crate::generated::qot_sub::Request { c2s };
    let body = request.encode_to_vec();
    let resp = client.request(PROTO_QOT_SUB, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_sub::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(())
}

/// Register/unregister push notifications for subscribed securities.
pub async fn reg_push(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
    sub_types: Vec<i32>,
    is_reg: bool,
) -> Result<(), QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_reg_qot_push::C2s {
        security_list,
        sub_type_list: sub_types,
        is_reg_or_un_reg: is_reg,
        ..Default::default()
    };

    let request = crate::generated::qot_reg_qot_push::Request { c2s };
    let body = request.encode_to_vec();
    let resp = client.request(PROTO_QOT_REG_PUSH, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_reg_qot_push::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub enum QuoteError {
    #[error("connection error: {0}")]
    Connection(#[from] ConnectionError),
    #[error("decode error: {0}")]
    Decode(String),
    #[error("server error (retType={ret_type}): {msg}")]
    Server { ret_type: i32, msg: String },
}
