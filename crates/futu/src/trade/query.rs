use prost::Message;
use crate::client::FutuClient;
use super::account::TradeError;

const PROTO_TRD_GET_ORDER_LIST: u32 = 2201;
const PROTO_TRD_GET_ORDER_FILL_LIST: u32 = 2211;
const PROTO_TRD_GET_POSITION_LIST: u32 = 2102;
const PROTO_TRD_GET_FUNDS: u32 = 2101;

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
) -> Result<crate::generated::trd_get_funds::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_get_funds::C2s {
        header,
        ..Default::default()
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
