use prost::Message;
use crate::client::FutuClient;
use super::account::TradeError;

const PROTO_TRD_GET_ORDER_LIST: u32 = 2201;
const PROTO_TRD_GET_ORDER_FILL_LIST: u32 = 2211;
const PROTO_TRD_GET_POSITION_LIST: u32 = 2102;
const PROTO_TRD_GET_FUNDS: u32 = 2101;
const PROTO_TRD_GET_HISTORY_ORDER_LIST: u32 = 2221;
const PROTO_TRD_GET_HISTORY_ORDER_FILL_LIST: u32 = 2222;
const PROTO_TRD_GET_MAX_TRD_QTYS: u32 = 2111;
const PROTO_TRD_GET_MARGIN_RATIO: u32 = 2223;
const PROTO_TRD_GET_ORDER_FEE: u32 = 2225;

/// Default lookback of history order/fill queries when no range is given
/// (same default as the official futu-api SDK).
pub const HISTORY_DEFAULT_LOOKBACK_DAYS: i64 = 90;

const SECS_PER_DAY: i64 = 86_400;

/// Format UNIX seconds as `YYYY-MM-DD HH:MM:SS` (UTC).
pub fn format_utc_datetime(unix_secs: i64) -> String {
    let days = unix_secs.div_euclid(SECS_PER_DAY);
    let secs = unix_secs.rem_euclid(SECS_PER_DAY);
    // Civil-from-days (Howard Hinnant), valid for the proleptic Gregorian calendar.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        year, month, day, secs / 3600, (secs % 3600) / 60, secs % 60,
    )
}

/// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant).
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Parse `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DD HH:MM:SS.ms` as
/// wall-clock seconds (the inverse of [`format_utc_datetime`]; fractions are
/// dropped).  Returns `None` for anything else.
pub fn parse_datetime_secs(value: &str) -> Option<i64> {
    let mut parts = value.trim().splitn(2, ' ');
    let mut date = parts.next()?.split('-');
    let year: i64 = date.next()?.parse().ok()?;
    let month: i64 = date.next()?.parse().ok()?;
    let day: i64 = date.next()?.parse().ok()?;
    if date.next().is_some() || !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    let mut secs = 0;
    if let Some(time) = parts.next() {
        let time = time.trim().split('.').next()?;
        let mut hms = time.split(':');
        let hour: i64 = hms.next()?.parse().ok()?;
        let minute: i64 = hms.next()?.parse().ok()?;
        let second: i64 = hms.next()?.parse().ok()?;
        if hms.next().is_some() || hour > 23 || minute > 59 || second > 60 {
            return None;
        }
        secs = hour * 3600 + minute * 60 + second;
    }
    Some(days_from_civil(year, month, day) * SECS_PER_DAY + secs)
}

/// Filter conditions for history order/fill queries.
///
/// OpenD rejects history queries without `beginTime`/`endTime`, so missing
/// bounds are filled in like the official futu-api SDK does, with a
/// [`HISTORY_DEFAULT_LOOKBACK_DAYS`] window:
/// - neither given: the window ends one day after `now_unix_secs` (covers every
///   market's local time);
/// - only `end_time`: the window starts that many days before it;
/// - only `begin_time`: the window ends that many days after it, but no later
///   than the default end.
///
/// The arithmetic is done on wall-clock values, so it is independent of the
/// market time zone the bounds are expressed in.
pub fn history_filter_conditions(
    begin_time: Option<String>,
    end_time: Option<String>,
    code_list: Vec<String>,
    now_unix_secs: i64,
) -> crate::generated::trd_common::TrdFilterConditions {
    let window = HISTORY_DEFAULT_LOOKBACK_DAYS * SECS_PER_DAY;
    let default_end = now_unix_secs + SECS_PER_DAY;
    let (begin_time, end_time) = match (begin_time, end_time) {
        (Some(begin), Some(end)) => (begin, end),
        (None, Some(end)) => {
            let end_secs = parse_datetime_secs(&end).unwrap_or(default_end);
            (format_utc_datetime(end_secs - window), end)
        }
        (Some(begin), None) => {
            let end_secs = parse_datetime_secs(&begin)
                .map(|b| (b + window).min(default_end))
                .unwrap_or(default_end);
            (begin, format_utc_datetime(end_secs))
        }
        (None, None) => (format_utc_datetime(default_end - window), format_utc_datetime(default_end)),
    };
    crate::generated::trd_common::TrdFilterConditions {
        code_list,
        begin_time: Some(begin_time),
        end_time: Some(end_time),
        ..Default::default()
    }
}

/// Current UNIX time in seconds.
pub fn unix_now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Get the order list.
///
/// `refresh_cache = Some(true)` makes OpenD fetch the list from the Futu
/// servers instead of answering from its cache (rate limited by OpenD).
pub async fn get_order_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
    refresh_cache: Option<bool>,
) -> Result<crate::generated::trd_get_order_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_order_list::C2s {
        header,
        filter_conditions: filter,
        refresh_cache,
        ..Default::default()
    };
    let request = crate::generated::trd_get_order_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_ORDER_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_order_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get order fills.
pub async fn get_order_fill_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
) -> Result<crate::generated::trd_get_order_fill_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_order_fill_list::C2s {
        header,
        filter_conditions: filter,
        ..Default::default()
    };
    let request = crate::generated::trd_get_order_fill_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_ORDER_FILL_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_order_fill_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get position list.
pub async fn get_position_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
) -> Result<crate::generated::trd_get_position_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_position_list::C2s {
        header,
        filter_conditions: filter,
        ..Default::default()
    };
    let request = crate::generated::trd_get_position_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_POSITION_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_position_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get account funds.
pub async fn get_funds(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    currency: Option<i32>,
) -> Result<crate::generated::trd_get_funds::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_funds::C2s {
        header,
        refresh_cache: None,
        currency,
    };
    let request = crate::generated::trd_get_funds::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_FUNDS, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_funds::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get historical order list.
pub async fn get_history_order_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
    filter_status_list: Vec<i32>,
) -> Result<crate::generated::trd_get_history_order_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let filter_conditions = filter.unwrap_or_default();
    let c2s = crate::generated::trd_get_history_order_list::C2s {
        header,
        filter_conditions,
        filter_status_list,
    };
    let request = crate::generated::trd_get_history_order_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_HISTORY_ORDER_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_history_order_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get historical order fill list.
pub async fn get_history_order_fill_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
) -> Result<crate::generated::trd_get_history_order_fill_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let filter_conditions = filter.unwrap_or_default();
    let c2s = crate::generated::trd_get_history_order_fill_list::C2s {
        header,
        filter_conditions,
    };
    let request = crate::generated::trd_get_history_order_fill_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_HISTORY_ORDER_FILL_LIST, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_history_order_fill_list::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get maximum tradeable quantities.
#[allow(clippy::too_many_arguments)]
pub async fn get_max_trd_qtys(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    order_type: i32,
    code: String,
    price: f64,
    sec_market: Option<i32>,
) -> Result<crate::generated::trd_get_max_trd_qtys::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_max_trd_qtys::C2s {
        header,
        order_type,
        code,
        price,
        sec_market,
        ..Default::default()
    };
    let request = crate::generated::trd_get_max_trd_qtys::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_MAX_TRD_QTYS, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_max_trd_qtys::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get margin ratio for securities.
pub async fn get_margin_ratio(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::trd_get_margin_ratio::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::trd_get_margin_ratio::C2s {
        header,
        security_list,
    };
    let request = crate::generated::trd_get_margin_ratio::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_MARGIN_RATIO, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_margin_ratio::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get order fee details.
pub async fn get_order_fee(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    order_id_ex_list: Vec<String>,
) -> Result<crate::generated::trd_get_order_fee::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_order_fee::C2s {
        header,
        order_id_ex_list,
    };
    let request = crate::generated::trd_get_order_fee::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_GET_ORDER_FEE, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_get_order_fee::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

#[cfg(test)]
mod tests {
    use prost::Message;

    const PROTO_TRD_GET_ORDER_LIST: u32 = 2201;
    const PROTO_TRD_GET_ORDER_FILL_LIST: u32 = 2211;
    const PROTO_TRD_GET_POSITION_LIST: u32 = 2102;
    const PROTO_TRD_GET_FUNDS: u32 = 2101;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_TRD_GET_ORDER_LIST, 2201);
        assert_eq!(PROTO_TRD_GET_ORDER_FILL_LIST, 2211);
        assert_eq!(PROTO_TRD_GET_POSITION_LIST, 2102);
        assert_eq!(PROTO_TRD_GET_FUNDS, 2101);
    }

    #[test]
    fn test_order_list_request_encode_decode() {
        let c2s = crate::generated::trd_get_order_list::C2s {
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 0,
                acc_id: 12345,
                trd_market: 1,
            },
            filter_conditions: Some(crate::generated::trd_common::TrdFilterConditions {
                code_list: vec!["00700".to_string()],
                id_list: vec![],
                begin_time: Some("2024-01-01".to_string()),
                end_time: Some("2024-12-31".to_string()),
                order_id_ex_list: vec![],
                filter_market: None,
            }),
            ..Default::default()
        };
        let request = crate::generated::trd_get_order_list::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_get_order_list::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.header.acc_id, 12345);
        let filter = decoded.c2s.filter_conditions.unwrap();
        assert_eq!(filter.code_list, vec!["00700"]);
        assert_eq!(filter.begin_time, Some("2024-01-01".to_string()));
    }

    #[test]
    fn test_format_utc_datetime() {
        assert_eq!(super::format_utc_datetime(0), "1970-01-01 00:00:00");
        assert_eq!(super::format_utc_datetime(951_782_400), "2000-02-29 00:00:00");
        assert_eq!(super::format_utc_datetime(1_718_400_000), "2024-06-14 21:20:00");
        assert_eq!(super::format_utc_datetime(1_735_689_599), "2024-12-31 23:59:59");
        assert_eq!(super::format_utc_datetime(-1), "1969-12-31 23:59:59");
    }

    #[test]
    fn test_history_filter_defaults_to_lookback_window() {
        let now = 1_718_400_000; // 2024-06-14 21:20:00 UTC
        let filter = super::history_filter_conditions(None, None, vec![], now);
        assert_eq!(filter.end_time.as_deref(), Some("2024-06-15 21:20:00"));
        assert_eq!(filter.begin_time.as_deref(), Some("2024-03-17 21:20:00"));
        assert!(filter.code_list.is_empty());
    }

    #[test]
    fn test_parse_datetime_secs_roundtrip() {
        assert_eq!(super::parse_datetime_secs("1970-01-01"), Some(0));
        assert_eq!(super::parse_datetime_secs("2000-02-29 00:00:00"), Some(951_782_400));
        assert_eq!(super::parse_datetime_secs("2024-06-14 21:20:00.123"), Some(1_718_400_000));
        assert_eq!(super::parse_datetime_secs("1969-12-31 23:59:59"), Some(-1));
        for secs in [-86_401_i64, 0, 951_782_400, 1_718_400_000, 4_102_444_799] {
            assert_eq!(super::parse_datetime_secs(&super::format_utc_datetime(secs)), Some(secs));
        }
        for bad in ["", "2024-13-01", "2024-01-32", "2024-01-01 24:00:00", "2024/01/01", "2024-01-01 10:00"] {
            assert_eq!(super::parse_datetime_secs(bad), None, "{bad}");
        }
    }

    #[test]
    fn test_history_filter_end_only_counts_back_from_end() {
        let now = 1_718_400_000; // 2024-06-14 21:20:00 UTC
        let filter = super::history_filter_conditions(None, Some("2024-01-31 23:59:59".to_string()), vec![], now);
        assert_eq!(filter.begin_time.as_deref(), Some("2023-11-02 23:59:59"));
        assert_eq!(filter.end_time.as_deref(), Some("2024-01-31 23:59:59"));
    }

    #[test]
    fn test_history_filter_begin_only_counts_forward_capped_at_now() {
        let now = 1_718_400_000; // 2024-06-14 21:20:00 UTC
        let old = super::history_filter_conditions(Some("2024-01-01".to_string()), None, vec![], now);
        assert_eq!(old.begin_time.as_deref(), Some("2024-01-01"));
        assert_eq!(old.end_time.as_deref(), Some("2024-03-31 00:00:00"));
        let recent = super::history_filter_conditions(Some("2024-06-01 00:00:00".to_string()), None, vec![], now);
        assert_eq!(recent.end_time.as_deref(), Some("2024-06-15 21:20:00"));
    }

    #[test]
    fn test_history_filter_keeps_explicit_bounds() {
        let filter = super::history_filter_conditions(
            Some("2024-01-01 00:00:00".to_string()),
            Some("2024-01-31 23:59:59".to_string()),
            vec!["00700".to_string()],
            0,
        );
        assert_eq!(filter.begin_time.as_deref(), Some("2024-01-01 00:00:00"));
        assert_eq!(filter.end_time.as_deref(), Some("2024-01-31 23:59:59"));
        assert_eq!(filter.code_list, vec!["00700"]);

        // The history request always carries the (required) time range on the wire.
        let c2s = crate::generated::trd_get_history_order_fill_list::C2s {
            header: crate::generated::trd_common::TrdHeader { trd_env: 1, acc_id: 1, trd_market: 1 },
            filter_conditions: filter,
        };
        let encoded = crate::generated::trd_get_history_order_fill_list::Request { c2s }.encode_to_vec();
        let decoded = crate::generated::trd_get_history_order_fill_list::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.filter_conditions.begin_time.as_deref(), Some("2024-01-01 00:00:00"));
    }

    #[test]
    fn test_funds_request_encode_decode() {
        let c2s = crate::generated::trd_get_funds::C2s {
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 1,
                acc_id: 67890,
                trd_market: 2,
            },
            ..Default::default()
        };
        let request = crate::generated::trd_get_funds::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_get_funds::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.header.trd_env, 1);
        assert_eq!(decoded.c2s.header.acc_id, 67890);
        assert_eq!(decoded.c2s.header.trd_market, 2);
        assert!(decoded.c2s.refresh_cache.is_none());
    }

    #[test]
    fn test_order_list_response_success() {
        let response = crate::generated::trd_get_order_list::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::trd_get_order_list::S2c {
                header: crate::generated::trd_common::TrdHeader {
                    trd_env: 0,
                    acc_id: 12345,
                    trd_market: 1,
                },
                order_list: vec![],
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::trd_get_order_list::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert!(s2c.order_list.is_empty());
    }

    #[test]
    fn test_order_list_response_error() {
        let response = crate::generated::trd_get_order_list::Response {
            ret_type: -1,
            ret_msg: Some("unauthorized".to_string()),
            err_code: Some(403),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::trd_get_order_list::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg.unwrap(), "unauthorized");
        assert!(decoded.s2c.is_none());
    }
}
