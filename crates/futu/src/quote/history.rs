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
#[allow(clippy::too_many_arguments)]
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_GET_KL, 3006);
        assert_eq!(PROTO_QOT_GET_HISTORY_KL, 3103);
    }

    #[test]
    fn test_kl_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 1,
            code: "00700".to_string(),
        };
        let c2s = crate::generated::qot_get_kl::C2s {
            rehab_type: 1,
            kl_type: 1,
            security,
            req_num: 100,
        };
        let request = crate::generated::qot_get_kl::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_kl::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.rehab_type, 1);
        assert_eq!(decoded.c2s.kl_type, 1);
        assert_eq!(decoded.c2s.security.market, 1);
        assert_eq!(decoded.c2s.security.code, "00700");
        assert_eq!(decoded.c2s.req_num, 100);
    }

    #[test]
    fn test_history_kl_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 11,
            code: "AAPL".to_string(),
        };
        let c2s = crate::generated::qot_get_history_kl::C2s {
            rehab_type: 0,
            kl_type: 1,
            security,
            begin_time: "2024-01-01".to_string(),
            end_time: "2024-12-31".to_string(),
            max_ack_kl_num: Some(500),
            ..Default::default()
        };
        let request = crate::generated::qot_get_history_kl::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded =
            crate::generated::qot_get_history_kl::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security.code, "AAPL");
        assert_eq!(decoded.c2s.begin_time, "2024-01-01");
        assert_eq!(decoded.c2s.end_time, "2024-12-31");
        assert_eq!(decoded.c2s.max_ack_kl_num, Some(500));
    }

    #[test]
    fn test_kline_roundtrip() {
        let kline = crate::generated::qot_common::KLine {
            time: "2024-06-15 09:30:00".to_string(),
            is_blank: false,
            high_price: Some(150.5),
            open_price: Some(148.0),
            low_price: Some(147.5),
            close_price: Some(149.8),
            last_close_price: Some(147.0),
            volume: Some(1000000),
            turnover: Some(1.5e8),
            turnover_rate: Some(0.05),
            pe: Some(25.3),
            change_rate: Some(1.9),
            timestamp: Some(1718430600.0),
        };
        let encoded = kline.encode_to_vec();
        let decoded = crate::generated::qot_common::KLine::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.time, "2024-06-15 09:30:00");
        assert!(!decoded.is_blank);
        assert_eq!(decoded.high_price, Some(150.5));
        assert_eq!(decoded.open_price, Some(148.0));
        assert_eq!(decoded.volume, Some(1000000));
    }

    #[test]
    fn test_history_kl_response_success() {
        let kline = crate::generated::qot_common::KLine {
            time: "2024-01-02".to_string(),
            is_blank: false,
            close_price: Some(100.0),
            ..Default::default()
        };
        let s2c = crate::generated::qot_get_history_kl::S2c {
            security: crate::generated::qot_common::Security {
                market: 1,
                code: "00700".to_string(),
            },
            kl_list: vec![kline],
            next_req_key: None,
        };
        let response = crate::generated::qot_get_history_kl::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let encoded = response.encode_to_vec();
        let decoded =
            crate::generated::qot_get_history_kl::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.kl_list.len(), 1);
        assert_eq!(s2c.kl_list[0].close_price, Some(100.0));
    }

    #[test]
    fn test_history_kl_response_error() {
        let response = crate::generated::qot_get_history_kl::Response {
            ret_type: -1,
            ret_msg: Some("not subscribed".to_string()),
            err_code: Some(3001),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded =
            crate::generated::qot_get_history_kl::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg, Some("not subscribed".to_string()));
        assert!(decoded.s2c.is_none());
    }
}
