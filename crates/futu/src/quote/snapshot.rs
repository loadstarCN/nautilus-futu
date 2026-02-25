use prost::Message;
use crate::client::FutuClient;
use super::subscribe::QuoteError;

const PROTO_QOT_GET_BASIC_QOT: u32 = 3004;
const PROTO_QOT_GET_SECURITY_SNAPSHOT: u32 = 3203;
const PROTO_QOT_GET_STATIC_INFO: u32 = 3202;
const PROTO_QOT_GET_TICKER: u32 = 3010;
const PROTO_QOT_GET_ORDER_BOOK: u32 = 3012;
const PROTO_QOT_STOCK_FILTER: u32 = 3215;
const PROTO_QOT_GET_PLATE_SECURITY: u32 = 3205;
const PROTO_QOT_GET_SUB_INFO: u32 = 3003;
const PROTO_QOT_GET_RT: u32 = 3008;
const PROTO_QOT_GET_BROKER: u32 = 3014;
const PROTO_QOT_REQUEST_REHAB: u32 = 3105;
const PROTO_QOT_GET_SUSPEND: u32 = 3201;
const PROTO_QOT_GET_PLATE_SET: u32 = 3204;
const PROTO_QOT_GET_REFERENCE: u32 = 3206;
const PROTO_QOT_GET_OWNER_PLATE: u32 = 3207;
const PROTO_QOT_GET_OPTION_CHAIN: u32 = 3209;
const PROTO_QOT_GET_WARRANT: u32 = 3210;
const PROTO_QOT_GET_CAPITAL_FLOW: u32 = 3211;
const PROTO_QOT_GET_CAPITAL_DISTRIBUTION: u32 = 3212;
const PROTO_QOT_GET_USER_SECURITY: u32 = 3213;
const PROTO_QOT_MODIFY_USER_SECURITY: u32 = 3214;
const PROTO_QOT_GET_CODE_CHANGE: u32 = 3216;
const PROTO_QOT_GET_IPO_LIST: u32 = 3217;
const PROTO_QOT_GET_FUTURE_INFO: u32 = 3218;
const PROTO_QOT_REQUEST_TRADE_DATE: u32 = 3219;
const PROTO_QOT_GET_OPTION_EXPIRATION_DATE: u32 = 3224;

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

/// Get order book for a single security.
pub async fn get_order_book(
    client: &FutuClient,
    market: i32,
    code: String,
    num: i32,
) -> Result<crate::generated::qot_get_order_book::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_order_book::C2s { security, num };
    let request = crate::generated::qot_get_order_book::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_ORDER_BOOK, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_order_book::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get ticker (trade ticks) for a single security.
pub async fn get_ticker(
    client: &FutuClient,
    market: i32,
    code: String,
    max_ret_num: i32,
) -> Result<crate::generated::qot_get_ticker::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_ticker::C2s { security, max_ret_num };
    let request = crate::generated::qot_get_ticker::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_TICKER, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_ticker::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Filter stocks by conditions (Qot_StockFilter, proto 3215).
#[allow(clippy::too_many_arguments)]
pub async fn stock_filter(
    client: &FutuClient,
    begin: i32,
    num: i32,
    market: i32,
    plate: Option<(i32, String)>,
    base_filters: Vec<crate::generated::qot_stock_filter::BaseFilter>,
    accumulate_filters: Vec<crate::generated::qot_stock_filter::AccumulateFilter>,
    financial_filters: Vec<crate::generated::qot_stock_filter::FinancialFilter>,
) -> Result<crate::generated::qot_stock_filter::Response, QuoteError> {
    let plate = plate.map(|(m, c)| crate::generated::qot_common::Security { market: m, code: c });

    let c2s = crate::generated::qot_stock_filter::C2s {
        begin,
        num,
        market,
        plate,
        base_filter_list: base_filters,
        accumulate_filter_list: accumulate_filters,
        financial_filter_list: financial_filters,
    };
    let request = crate::generated::qot_stock_filter::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_STOCK_FILTER, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_stock_filter::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get securities in a plate/sector (Qot_GetPlateSecurity, proto 3205).
pub async fn get_plate_security(
    client: &FutuClient,
    plate_market: i32,
    plate_code: String,
    sort_field: Option<i32>,
    ascend: Option<bool>,
) -> Result<crate::generated::qot_get_plate_security::Response, QuoteError> {
    let plate = crate::generated::qot_common::Security { market: plate_market, code: plate_code };
    let c2s = crate::generated::qot_get_plate_security::C2s {
        plate,
        sort_field,
        ascend,
    };
    let request = crate::generated::qot_get_plate_security::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_PLATE_SECURITY, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_plate_security::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get subscription info.
pub async fn get_sub_info(
    client: &FutuClient,
    is_req_all_conn: Option<bool>,
) -> Result<crate::generated::qot_get_sub_info::Response, QuoteError> {
    let c2s = crate::generated::qot_get_sub_info::C2s { is_req_all_conn };
    let request = crate::generated::qot_get_sub_info::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_SUB_INFO, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_sub_info::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get real-time (time-sharing) data for a single security.
pub async fn get_rt(
    client: &FutuClient,
    market: i32,
    code: String,
) -> Result<crate::generated::qot_get_rt::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_rt::C2s { security };
    let request = crate::generated::qot_get_rt::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_RT, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_rt::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get broker queue for a single security.
pub async fn get_broker(
    client: &FutuClient,
    market: i32,
    code: String,
) -> Result<crate::generated::qot_get_broker::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_broker::C2s { security };
    let request = crate::generated::qot_get_broker::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_BROKER, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_broker::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get rehabilitation (adjustment) data for securities.
pub async fn get_rehab(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_rehab::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_rehab::C2s { security_list };
    let request = crate::generated::qot_get_rehab::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_REQUEST_REHAB, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_rehab::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get suspension info for securities.
pub async fn get_suspend(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
    begin_time: String,
    end_time: String,
) -> Result<crate::generated::qot_get_suspend::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_suspend::C2s {
        security_list,
        begin_time,
        end_time,
    };
    let request = crate::generated::qot_get_suspend::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_SUSPEND, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_suspend::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get plate set (sector list) for a market.
pub async fn get_plate_set(
    client: &FutuClient,
    market: i32,
    plate_set_type: i32,
) -> Result<crate::generated::qot_get_plate_set::Response, QuoteError> {
    let c2s = crate::generated::qot_get_plate_set::C2s { market, plate_set_type };
    let request = crate::generated::qot_get_plate_set::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_PLATE_SET, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_plate_set::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get reference data (related securities) for a single security.
pub async fn get_reference(
    client: &FutuClient,
    market: i32,
    code: String,
    reference_type: i32,
) -> Result<crate::generated::qot_get_reference::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_reference::C2s { security, reference_type };
    let request = crate::generated::qot_get_reference::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_REFERENCE, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_reference::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get owner plates (sectors) for securities.
pub async fn get_owner_plate(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_owner_plate::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_owner_plate::C2s { security_list };
    let request = crate::generated::qot_get_owner_plate::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_OWNER_PLATE, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_owner_plate::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get option chain for an underlying security.
#[allow(clippy::too_many_arguments)]
pub async fn get_option_chain(
    client: &FutuClient,
    owner_market: i32,
    owner_code: String,
    begin_time: String,
    end_time: String,
    option_type: Option<i32>,
    condition: Option<i32>,
    index_option_type: Option<i32>,
    data_filter: Option<crate::generated::qot_get_option_chain::DataFilter>,
) -> Result<crate::generated::qot_get_option_chain::Response, QuoteError> {
    let owner = crate::generated::qot_common::Security { market: owner_market, code: owner_code };
    let c2s = crate::generated::qot_get_option_chain::C2s {
        owner,
        r#type: option_type,
        condition,
        begin_time,
        end_time,
        index_option_type,
        data_filter,
    };
    let request = crate::generated::qot_get_option_chain::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_OPTION_CHAIN, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_option_chain::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get warrant list.
#[allow(clippy::too_many_arguments)]
pub async fn get_warrant(
    client: &FutuClient,
    begin: i32,
    num: i32,
    sort_field: i32,
    ascend: bool,
    owner: Option<(i32, String)>,
    type_list: Vec<i32>,
    issuer_list: Vec<i32>,
) -> Result<crate::generated::qot_get_warrant::Response, QuoteError> {
    let owner = owner.map(|(m, c)| crate::generated::qot_common::Security { market: m, code: c });

    let c2s = crate::generated::qot_get_warrant::C2s {
        begin,
        num,
        sort_field,
        ascend,
        owner,
        type_list,
        issuer_list,
        ..Default::default()
    };
    let request = crate::generated::qot_get_warrant::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_WARRANT, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_warrant::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get capital flow for a single security.
pub async fn get_capital_flow(
    client: &FutuClient,
    market: i32,
    code: String,
    period_type: Option<i32>,
) -> Result<crate::generated::qot_get_capital_flow::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_capital_flow::C2s {
        security,
        period_type,
        ..Default::default()
    };
    let request = crate::generated::qot_get_capital_flow::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_CAPITAL_FLOW, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_capital_flow::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get capital distribution for a single security.
pub async fn get_capital_distribution(
    client: &FutuClient,
    market: i32,
    code: String,
) -> Result<crate::generated::qot_get_capital_distribution::Response, QuoteError> {
    let security = crate::generated::qot_common::Security { market, code };
    let c2s = crate::generated::qot_get_capital_distribution::C2s { security };
    let request = crate::generated::qot_get_capital_distribution::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_CAPITAL_DISTRIBUTION, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_capital_distribution::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get user security group.
pub async fn get_user_security(
    client: &FutuClient,
    group_name: String,
) -> Result<crate::generated::qot_get_user_security::Response, QuoteError> {
    let c2s = crate::generated::qot_get_user_security::C2s { group_name };
    let request = crate::generated::qot_get_user_security::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_USER_SECURITY, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_user_security::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Modify user security group.
pub async fn modify_user_security(
    client: &FutuClient,
    group_name: String,
    op: i32,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_modify_user_security::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_modify_user_security::C2s {
        group_name,
        op,
        security_list,
    };
    let request = crate::generated::qot_modify_user_security::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_MODIFY_USER_SECURITY, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_modify_user_security::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get code change info for securities.
pub async fn get_code_change(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
    type_list: Vec<i32>,
) -> Result<crate::generated::qot_get_code_change::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_code_change::C2s {
        place_holder: None,
        security_list,
        time_filter_list: vec![],
        type_list,
    };
    let request = crate::generated::qot_get_code_change::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_CODE_CHANGE, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_code_change::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get IPO list for a market.
pub async fn get_ipo_list(
    client: &FutuClient,
    market: i32,
) -> Result<crate::generated::qot_get_ipo_list::Response, QuoteError> {
    let c2s = crate::generated::qot_get_ipo_list::C2s { market };
    let request = crate::generated::qot_get_ipo_list::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_IPO_LIST, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_ipo_list::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get future info for securities.
pub async fn get_future_info(
    client: &FutuClient,
    securities: Vec<(i32, String)>,
) -> Result<crate::generated::qot_get_future_info::Response, QuoteError> {
    let security_list: Vec<crate::generated::qot_common::Security> = securities
        .into_iter()
        .map(|(market, code)| crate::generated::qot_common::Security { market, code })
        .collect();

    let c2s = crate::generated::qot_get_future_info::C2s { security_list };
    let request = crate::generated::qot_get_future_info::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_FUTURE_INFO, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_future_info::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Request trade dates for a market.
pub async fn request_trade_date(
    client: &FutuClient,
    market: i32,
    begin_time: String,
    end_time: String,
    security: Option<(i32, String)>,
) -> Result<crate::generated::qot_request_trade_date::Response, QuoteError> {
    let security = security.map(|(m, c)| crate::generated::qot_common::Security { market: m, code: c });

    let c2s = crate::generated::qot_request_trade_date::C2s {
        market,
        begin_time,
        end_time,
        security,
    };
    let request = crate::generated::qot_request_trade_date::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_REQUEST_TRADE_DATE, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_request_trade_date::Response::decode(resp.body.as_slice())
        .map_err(|e| QuoteError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(QuoteError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Get option expiration dates for an underlying security.
pub async fn get_option_expiration_date(
    client: &FutuClient,
    owner_market: i32,
    owner_code: String,
    index_option_type: Option<i32>,
) -> Result<crate::generated::qot_get_option_expiration_date::Response, QuoteError> {
    let owner = crate::generated::qot_common::Security { market: owner_market, code: owner_code };
    let c2s = crate::generated::qot_get_option_expiration_date::C2s {
        owner,
        index_option_type,
    };
    let request = crate::generated::qot_get_option_expiration_date::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_QOT_GET_OPTION_EXPIRATION_DATE, &body).await
        .map_err(QuoteError::Connection)?;

    let response = crate::generated::qot_get_option_expiration_date::Response::decode(resp.body.as_slice())
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
    const PROTO_QOT_GET_TICKER: u32 = 3010;
    const PROTO_QOT_GET_ORDER_BOOK: u32 = 3012;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_GET_BASIC_QOT, 3004);
        assert_eq!(PROTO_QOT_GET_STATIC_INFO, 3202);
        assert_eq!(PROTO_QOT_GET_SECURITY_SNAPSHOT, 3203);
        assert_eq!(PROTO_QOT_GET_TICKER, 3010);
        assert_eq!(PROTO_QOT_GET_ORDER_BOOK, 3012);
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

    #[test]
    fn test_order_book_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 1,
            code: "00700".to_string(),
        };
        let c2s = crate::generated::qot_get_order_book::C2s {
            security,
            num: 10,
        };
        let request = crate::generated::qot_get_order_book::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_order_book::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security.market, 1);
        assert_eq!(decoded.c2s.security.code, "00700");
        assert_eq!(decoded.c2s.num, 10);
    }

    #[test]
    fn test_order_book_response_success() {
        let response = crate::generated::qot_get_order_book::Response {
            ret_type: 0,
            ret_msg: Some("success".to_string()),
            err_code: None,
            s2c: Some(crate::generated::qot_get_order_book::S2c {
                security: crate::generated::qot_common::Security {
                    market: 1,
                    code: "00700".to_string(),
                },
                name: Some("TENCENT".to_string()),
                order_book_ask_list: vec![crate::generated::qot_common::OrderBook {
                    price: 346.0,
                    volume: 500,
                    order_count: 10,
                    detail_list: vec![],
                }],
                order_book_bid_list: vec![crate::generated::qot_common::OrderBook {
                    price: 345.0,
                    volume: 1000,
                    order_count: 20,
                    detail_list: vec![],
                }],
                svr_recv_time_bid: None,
                svr_recv_time_bid_timestamp: None,
                svr_recv_time_ask: None,
                svr_recv_time_ask_timestamp: None,
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_order_book::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.order_book_ask_list.len(), 1);
        assert_eq!(s2c.order_book_bid_list.len(), 1);
        assert_eq!(s2c.order_book_ask_list[0].price, 346.0);
        assert_eq!(s2c.order_book_bid_list[0].price, 345.0);
    }

    #[test]
    fn test_order_book_response_error() {
        let response = crate::generated::qot_get_order_book::Response {
            ret_type: -1,
            ret_msg: Some("not subscribed".to_string()),
            err_code: Some(1002),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_order_book::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg.unwrap(), "not subscribed");
        assert!(decoded.s2c.is_none());
    }

    #[test]
    fn test_ticker_request_encode_decode() {
        let security = crate::generated::qot_common::Security {
            market: 11,
            code: "AAPL".to_string(),
        };
        let c2s = crate::generated::qot_get_ticker::C2s {
            security,
            max_ret_num: 200,
        };
        let request = crate::generated::qot_get_ticker::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_ticker::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.security.market, 11);
        assert_eq!(decoded.c2s.security.code, "AAPL");
        assert_eq!(decoded.c2s.max_ret_num, 200);
    }

    #[test]
    fn test_ticker_response_success() {
        let response = crate::generated::qot_get_ticker::Response {
            ret_type: 0,
            ret_msg: Some("success".to_string()),
            err_code: None,
            s2c: Some(crate::generated::qot_get_ticker::S2c {
                security: crate::generated::qot_common::Security {
                    market: 11,
                    code: "AAPL".to_string(),
                },
                name: Some("Apple Inc.".to_string()),
                ticker_list: vec![crate::generated::qot_common::Ticker {
                    time: "2024-01-01 10:00:00".to_string(),
                    sequence: 12345,
                    dir: 1,
                    price: 195.5,
                    volume: 100,
                    turnover: 19550.0,
                    timestamp: Some(1704067200.0),
                    ..Default::default()
                }],
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_ticker::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.ticker_list.len(), 1);
        assert_eq!(s2c.ticker_list[0].price, 195.5);
        assert_eq!(s2c.ticker_list[0].sequence, 12345);
    }

    #[test]
    fn test_ticker_response_error() {
        let response = crate::generated::qot_get_ticker::Response {
            ret_type: -1,
            ret_msg: Some("quota exceeded".to_string()),
            err_code: Some(2003),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_ticker::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg.unwrap(), "quota exceeded");
        assert!(decoded.s2c.is_none());
    }

    #[test]
    fn test_stock_filter_proto_id() {
        assert_eq!(super::PROTO_QOT_STOCK_FILTER, 3215);
    }

    #[test]
    fn test_stock_filter_request_encode_decode() {
        let base_filter = crate::generated::qot_stock_filter::BaseFilter {
            field_name: 1,
            filter_min: Some(10.0),
            filter_max: Some(100.0),
            is_no_filter: None,
            sort_dir: Some(2),
        };
        let c2s = crate::generated::qot_stock_filter::C2s {
            begin: 0,
            num: 50,
            market: 1,
            plate: None,
            base_filter_list: vec![base_filter],
            accumulate_filter_list: vec![],
            financial_filter_list: vec![],
        };
        let request = crate::generated::qot_stock_filter::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_stock_filter::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.begin, 0);
        assert_eq!(decoded.c2s.num, 50);
        assert_eq!(decoded.c2s.market, 1);
        assert_eq!(decoded.c2s.base_filter_list.len(), 1);
        assert_eq!(decoded.c2s.base_filter_list[0].field_name, 1);
        assert_eq!(decoded.c2s.base_filter_list[0].filter_min, Some(10.0));
    }

    #[test]
    fn test_stock_filter_response_success() {
        let stock = crate::generated::qot_stock_filter::StockData {
            security: crate::generated::qot_common::Security {
                market: 1,
                code: "00700".to_string(),
            },
            name: "TENCENT".to_string(),
            base_data_list: vec![crate::generated::qot_stock_filter::BaseData {
                field_name: 1,
                value: 350.0,
            }],
            accumulate_data_list: vec![],
            financial_data_list: vec![],
        };
        let response = crate::generated::qot_stock_filter::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::qot_stock_filter::S2c {
                last_page: true,
                all_count: 1,
                data_list: vec![stock],
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_stock_filter::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert!(s2c.last_page);
        assert_eq!(s2c.all_count, 1);
        assert_eq!(s2c.data_list.len(), 1);
        assert_eq!(s2c.data_list[0].security.code, "00700");
        assert_eq!(s2c.data_list[0].name, "TENCENT");
    }

    #[test]
    fn test_get_plate_security_proto_id() {
        assert_eq!(super::PROTO_QOT_GET_PLATE_SECURITY, 3205);
    }

    #[test]
    fn test_get_plate_security_request_encode_decode() {
        let plate = crate::generated::qot_common::Security {
            market: 1,
            code: "BK1001".to_string(),
        };
        let c2s = crate::generated::qot_get_plate_security::C2s {
            plate,
            sort_field: Some(1),
            ascend: Some(true),
        };
        let request = crate::generated::qot_get_plate_security::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::qot_get_plate_security::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.plate.market, 1);
        assert_eq!(decoded.c2s.plate.code, "BK1001");
        assert_eq!(decoded.c2s.sort_field, Some(1));
        assert_eq!(decoded.c2s.ascend, Some(true));
    }

    #[test]
    fn test_get_plate_security_response_success() {
        let info = crate::generated::qot_common::SecurityStaticInfo {
            basic: crate::generated::qot_common::SecurityStaticBasic {
                security: crate::generated::qot_common::Security {
                    market: 1,
                    code: "00700".to_string(),
                },
                name: "TENCENT".to_string(),
                lot_size: 100,
                sec_type: 3,
                list_time: "2004-06-16".to_string(),
                ..Default::default()
            },
            ..Default::default()
        };
        let response = crate::generated::qot_get_plate_security::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::qot_get_plate_security::S2c {
                static_info_list: vec![info],
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::qot_get_plate_security::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.static_info_list.len(), 1);
        assert_eq!(s2c.static_info_list[0].basic.security.code, "00700");
        assert_eq!(s2c.static_info_list[0].basic.name, "TENCENT");
    }
}
