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

/// Get the order list.
pub async fn get_order_list(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    filter: Option<crate::generated::trd_common::TrdFilterConditions>,
) -> Result<crate::generated::trd_get_order_list::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_order_list::C2s {
        header,
        filter_conditions: filter,
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
