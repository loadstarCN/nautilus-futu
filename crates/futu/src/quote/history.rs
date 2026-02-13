use prost::Message;
use crate::client::FutuClient;
use super::subscribe::QuoteError;

const PROTO_QOT_GET_KL: u32 = 3006;
const PROTO_QOT_GET_HISTORY_KL: u32 = 3103;

/// Get K-line (candlestick) data for a subscribed security.
pub async fn get_kl(
    client: &FutuClient,
    market: i32,
    code: String,
    rehab_type: i32,
    kl_type: i32,
    req_count: i32,
) -> Result<crate::generated::qot_get_kl::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_kl::C2s {
        rehab_type,
        kl_type,
        security,
        req_num: req_count,
    };
    let request = crate::generated::qot_get_kl::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_KL, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_kl::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get historical K-line data.
pub async fn get_history_kl(
    client: &FutuClient,
    market: i32,
    code: String,
    rehab_type: i32,
    kl_type: i32,
    begin_time: String,
    end_time: String,
    max_count: Option<i32>,
) -> Result<crate::generated::qot_get_history_kl::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_history_kl::C2s {
        rehab_type,
        kl_type,
        security,
        begin_time,
        end_time,
        max_ack_kl_num: max_count,
        ..Default::default()
    };
    let request = crate::generated::qot_get_history_kl::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_HISTORY_KL, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_history_kl::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}
