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

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_SUB, 3001);
        assert_eq!(PROTO_QOT_REG_PUSH, 3002);
    }

    #[test]
    fn test_subscribe_request_encode_decode() {
        let securities = vec![
            crate::generated::qot_common::Security {
                market: 1,
                code: "00700".to_string(),
            },
            crate::generated::qot_common::Security {
                market: 11,
                code: "AAPL".to_string(),
            },
        ];
        let c2s = crate::generated::qot_sub::C2s {
            security_list: securities,
            sub_type_list: vec![1, 4],
            is_sub_or_un_sub: true,
            is_reg_or_un_reg_push: Some(true),
            ..Default::default()
        };
        let request = crate::generated::qot_sub::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_sub::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security_list.len(), 2);
        assert_eq!(decoded.c2s.security_list[0].code, "00700");
        assert_eq!(decoded.c2s.security_list[1].code, "AAPL");
        assert_eq!(decoded.c2s.sub_type_list, vec![1, 4]);
        assert!(decoded.c2s.is_sub_or_un_sub);
        assert_eq!(decoded.c2s.is_reg_or_un_reg_push, Some(true));
    }

    #[test]
    fn test_subscribe_response_success() {
        let response = crate::generated::qot_sub::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::qot_sub::S2c {}),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_sub::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        assert!(decoded.s2c.is_some());
    }

    #[test]
    fn test_subscribe_response_error() {
        let response = crate::generated::qot_sub::Response {
            ret_type: -1,
            ret_msg: Some("quota exceeded".to_string()),
            err_code: Some(2002),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_sub::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg, Some("quota exceeded".to_string()));
        assert_eq!(decoded.err_code, Some(2002));
        assert!(decoded.s2c.is_none());
    }
}
