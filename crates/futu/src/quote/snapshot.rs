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

#[cfg(test)]
mod tests {
    use prost::Message;

    const PROTO_QOT_GET_BASIC_QOT: u32 = 3004;
    const PROTO_QOT_GET_STATIC_INFO: u32 = 3202;
    const PROTO_QOT_GET_SECURITY_SNAPSHOT: u32 = 3203;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_GET_BASIC_QOT, 3004);
        assert_eq!(PROTO_QOT_GET_STATIC_INFO, 3202);
        assert_eq!(PROTO_QOT_GET_SECURITY_SNAPSHOT, 3203);
    }

    #[test]
    fn test_basic_qot_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 1,
            code: "00700".to_string(),
        };
        let c2s = crate::generated::qot_get_basic_qot::C2s {
            security_list: vec![security],
        };
        let request = crate::generated::qot_get_basic_qot::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_basic_qot::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security_list.len(), 1);
        assert_eq!(decoded.c2s.security_list[0].market, 1);
        assert_eq!(decoded.c2s.security_list[0].code, "00700");
    }

    #[test]
    fn test_static_info_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 11,
            code: "AAPL".to_string(),
        };
        let c2s = crate::generated::qot_get_static_info::C2s {
            security_list: vec![security],
            ..Default::default()
        };
        let request = crate::generated::qot_get_static_info::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_static_info::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security_list.len(), 1);
        assert_eq!(decoded.c2s.security_list[0].code, "AAPL");
    }

    #[test]
    fn test_snapshot_request_encode_decode() {
        let securities = vec![
            crate::generated::qot_common::Security { market: 1, code: "00700".to_string() },
            crate::generated::qot_common::Security { market: 11, code: "TSLA".to_string() },
        ];
        let c2s = crate::generated::qot_get_security_snapshot::C2s { security_list: securities };
        let request = crate::generated::qot_get_security_snapshot::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_security_snapshot::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security_list.len(), 2);
        assert_eq!(decoded.c2s.security_list[1].code, "TSLA");
    }

    #[test]
    fn test_basic_qot_response_success() {
        let response = crate::generated::qot_get_basic_qot::Response {
            ret_type: 0,
            ret_msg: Some("success".to_string()),
            err_code: None,
            s2c: Some(crate::generated::qot_get_basic_qot::S2c {
                basic_qot_list: vec![],
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_basic_qot::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        assert!(decoded.s2c.is_some());
    }

    #[test]
    fn test_basic_qot_response_error() {
        let response = crate::generated::qot_get_basic_qot::Response {
            ret_type: -1,
            ret_msg: Some("no permission".to_string()),
            err_code: Some(1001),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_basic_qot::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg.unwrap(), "no permission");
        assert!(decoded.s2c.is_none());
    }
}
