use prost::Message;
use crate::client::FutuClient;
use super::subscribe::QuoteError;

const PROTO_QOT_GET_BASIC_QOT: u32 = 3004;
const PROTO_QOT_GET_SECURITY_SNAPSHOT: u32 = 3203;
const PROTO_QOT_GET_STATIC_INFO: u32 = 3202;

/// Get basic quote data for securities.
pub async fn get_basic_qot(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_basic_qot::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_basic_qot::C2s { security_list };
    let request = crate::generated::qot_get_basic_qot::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_BASIC_QOT, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_basic_qot::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get static info for securities.
pub async fn get_static_info(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_static_info::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_static_info::C2s {
        security_list,
        ..Default::default()
    };
    let request = crate::generated::qot_get_static_info::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_STATIC_INFO, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_static_info::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get security snapshot.
pub async fn get_security_snapshot(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_security_snapshot::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_security_snapshot::C2s { security_list };
    let request = crate::generated::qot_get_security_snapshot::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_SECURITY_SNAPSHOT, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_security_snapshot::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}
