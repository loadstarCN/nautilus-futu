use prost::Message;
use crate::client::FutuClient;
use super::account::TradeError;

const PROTO_TRD_PLACE_ORDER: u32 = 2202;
const PROTO_TRD_MODIFY_ORDER: u32 = 2205;

/// Place a new order.
#[allow(clippy::too_many_arguments)]
pub async fn place_order(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    trd_side: i32,
    order_type: i32,
    code: String,
    qty: f64,
    price: Option<f64>,
    adjust_limit: Option<f64>,
    sec_market: Option<i32>,
    remark: Option<String>,
    time_in_force: Option<i32>,
    fill_outside_rth: Option<bool>,
    aux_price: Option<f64>,
    trail_type: Option<i32>,
    trail_value: Option<f64>,
    trail_spread: Option<f64>,
) -> Result<crate::generated::trd_place_order::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_place_order::C2s {
        packet_id: crate::generated::common::PacketId {
            conn_id: 0,
            serial_no: 0,
        },
        header,
        trd_side,
        order_type,
        code,
        qty,
        price,
        adjust_price: None,
        adjust_side_and_limit: adjust_limit,
        sec_market,
        remark,
        time_in_force,
        fill_outside_rth,
        aux_price,
        trail_type,
        trail_value,
        trail_spread,
        ..Default::default()
    };

    let request = crate::generated::trd_place_order::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_PLACE_ORDER, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_place_order::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}

/// Modify an existing order.
#[allow(clippy::too_many_arguments)]
pub async fn modify_order(
    client: &FutuClient,
    trd_env: i32,
    acc_id: u64,
    trd_market: i32,
    order_id: u64,
    modify_order_op: i32,
    qty: Option<f64>,
    price: Option<f64>,
    adjust_limit: Option<f64>,
) -> Result<crate::generated::trd_modify_order::Response, TradeError> {
    let header = crate::generated::trd_common::TrdHeader {
        trd_env,
        acc_id,
        trd_market,
    };

    let c2s = crate::generated::trd_modify_order::C2s {
        packet_id: crate::generated::common::PacketId {
            conn_id: 0,
            serial_no: 0,
        },
        header,
        order_id,
        modify_order_op,
        qty,
        price,
        adjust_price: None,
        adjust_side_and_limit: adjust_limit,
        ..Default::default()
    };

    let request = crate::generated::trd_modify_order::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_MODIFY_ORDER, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_modify_order::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(response)
}
