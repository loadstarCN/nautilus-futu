use prost::Message;
use crate::client::FutuClient;
use super::subscribe::QuoteError;

const PROTO_QOT_GET_KL: u32 = 3006;
const PROTO_QOT_GET_HISTORY_KL: u32 = 3103;

/// OpenD returns at most this many K-lines per `Qot_RequestHistoryKL` call and
/// hands back `next_req_key` when more are available.
pub const HISTORY_KL_PAGE_SIZE: i32 = 1000;

/// Safety cap on pages fetched by [`get_history_kl_all`] so a runaway request
/// cannot burn the whole 30-day history quota.
pub const HISTORY_KL_MAX_PAGES: usize = 50;

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

/// Get one page of historical K-line data.
///
/// Pass the `next_req_key` from a previous response to fetch the following page.
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
    next_req_key: Option<Vec<u8>>,
) -> Result<crate::generated::qot_get_history_kl::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_history_kl::C2s {
        rehab_type,
        kl_type,
        security,
        begin_time,
        end_time,
        max_ack_kl_num: max_count,
        next_req_key,
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

/// Fetch historical K-lines across pages until `max_count` bars are collected,
/// the server reports no further page, or [`HISTORY_KL_MAX_PAGES`] is reached.
///
/// `max_count == None` means "everything in the time range".
#[allow(clippy::too_many_arguments)]
pub async fn get_history_kl_all(
    client: &FutuClient,
    market: i32,
    code: String,
    rehab_type: i32,
    kl_type: i32,
    begin_time: String,
    end_time: String,
    max_count: Option<i32>,
) -> Result<Vec<crate::generated::qot_common::KLine>, QuoteError> {
    let mut collected: Vec<crate::generated::qot_common::KLine> = Vec::new();
    let mut next_req_key: Option<Vec<u8>> = None;

    for page in 0..HISTORY_KL_MAX_PAGES {
        let remaining = max_count.map(|m| m - collected.len() as i32);
        if matches!(remaining, Some(r) if r <= 0) {
            break;
        }
        let page_size = Some(remaining.map_or(HISTORY_KL_PAGE_SIZE, |r| r.min(HISTORY_KL_PAGE_SIZE)));

        let response = get_history_kl(
            client, market, code.clone(), rehab_type, kl_type,
            begin_time.clone(), end_time.clone(), page_size, next_req_key.take(),
        ).await?;

        let Some(s2c) = response.s2c else { break };
        let got = s2c.kl_list.len();
        collected.extend(s2c.kl_list);
        tracing::debug!("history KL page {} for {}: {} bars (total {})", page + 1, code, got, collected.len());

        match s2c.next_req_key {
            Some(key) if !key.is_empty() && got > 0 => next_req_key = Some(key),
            _ => break,
        }
    }

    if let Some(max) = max_count {
        if collected.len() > max as usize {
            collected.truncate(max as usize);
        }
    }
    Ok(collected)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_GET_KL, 3006);
        assert_eq!(PROTO_QOT_GET_HISTORY_KL, 3103);
        assert_eq!(HISTORY_KL_PAGE_SIZE, 1000);
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
            next_req_key: Some(vec![1, 2, 3]),
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
        assert_eq!(decoded.c2s.next_req_key, Some(vec![1, 2, 3]));
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
