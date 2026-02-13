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

    let conn_id = client.connection().conn_id().await;
    let serial_no = client.connection().next_serial();
    let c2s = crate::generated::trd_place_order::C2s {
        packet_id: crate::generated::common::PacketId {
            conn_id,
            serial_no,
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

    let conn_id = client.connection().conn_id().await;
    let serial_no = client.connection().next_serial();
    let c2s = crate::generated::trd_modify_order::C2s {
        packet_id: crate::generated::common::PacketId {
            conn_id,
            serial_no,
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

#[cfg(test)]
mod tests {
    use prost::Message;

    const PROTO_TRD_PLACE_ORDER: u32 = 2202;
    const PROTO_TRD_MODIFY_ORDER: u32 = 2205;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_TRD_PLACE_ORDER, 2202);
        assert_eq!(PROTO_TRD_MODIFY_ORDER, 2205);
    }

    #[test]
    fn test_place_order_request_encode_decode() {
        let c2s = crate::generated::trd_place_order::C2s {
            packet_id: crate::generated::common::PacketId {
                conn_id: 100,
                serial_no: 1,
            },
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 0,
                acc_id: 12345,
                trd_market: 1,
            },
            trd_side: 1,
            order_type: 1,
            code: "00700".to_string(),
            qty: 100.0,
            price: Some(350.0),
            sec_market: Some(1),
            remark: Some("test order".to_string()),
            time_in_force: Some(0),
            fill_outside_rth: Some(false),
            aux_price: Some(345.0),
            trail_type: Some(1),
            trail_value: Some(5.0),
            trail_spread: Some(0.5),
            ..Default::default()
        };
        let request = crate::generated::trd_place_order::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_place_order::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.code, "00700");
        assert_eq!(decoded.c2s.qty, 100.0);
        assert_eq!(decoded.c2s.price, Some(350.0));
        assert_eq!(decoded.c2s.sec_market, Some(1));
        assert_eq!(decoded.c2s.header.acc_id, 12345);
        assert_eq!(decoded.c2s.remark, Some("test order".to_string()));
    }

    #[test]
    fn test_place_order_optional_fields() {
        let c2s = crate::generated::trd_place_order::C2s {
            packet_id: crate::generated::common::PacketId {
                conn_id: 1,
                serial_no: 1,
            },
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 0,
                acc_id: 1,
                trd_market: 1,
            },
            trd_side: 1,
            order_type: 2,
            code: "AAPL".to_string(),
            qty: 10.0,
            price: None,
            adjust_price: None,
            adjust_side_and_limit: None,
            sec_market: None,
            remark: None,
            time_in_force: None,
            fill_outside_rth: None,
            aux_price: None,
            trail_type: None,
            trail_value: None,
            trail_spread: None,
            ..Default::default()
        };
        let request = crate::generated::trd_place_order::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_place_order::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.code, "AAPL");
        assert_eq!(decoded.c2s.order_type, 2);
        assert!(decoded.c2s.price.is_none());
        assert!(decoded.c2s.sec_market.is_none());
        assert!(decoded.c2s.remark.is_none());
    }

    #[test]
    fn test_modify_order_request_encode_decode() {
        let c2s = crate::generated::trd_modify_order::C2s {
            packet_id: crate::generated::common::PacketId {
                conn_id: 200,
                serial_no: 5,
            },
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 1,
                acc_id: 99999,
                trd_market: 2,
            },
            order_id: 123456789,
            modify_order_op: 1,
            qty: Some(50.0),
            price: Some(175.5),
            ..Default::default()
        };
        let request = crate::generated::trd_modify_order::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_modify_order::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.order_id, 123456789);
        assert_eq!(decoded.c2s.modify_order_op, 1);
        assert_eq!(decoded.c2s.qty, Some(50.0));
        assert_eq!(decoded.c2s.price, Some(175.5));
        assert_eq!(decoded.c2s.header.trd_env, 1);
    }

    #[test]
    fn test_place_order_response_success() {
        let response = crate::generated::trd_place_order::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::trd_place_order::S2c {
                header: crate::generated::trd_common::TrdHeader {
                    trd_env: 0,
                    acc_id: 12345,
                    trd_market: 1,
                },
                order_id: Some(987654321),
                order_id_ex: Some("ORD-987654321".to_string()),
            }),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::trd_place_order::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.order_id, Some(987654321));
        assert_eq!(s2c.order_id_ex, Some("ORD-987654321".to_string()));
    }

    #[test]
    fn test_place_order_response_error() {
        let response = crate::generated::trd_place_order::Response {
            ret_type: -1,
            ret_msg: Some("insufficient funds".to_string()),
            err_code: Some(2001),
            s2c: None,
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::trd_place_order::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, -1);
        assert_eq!(decoded.ret_msg.unwrap(), "insufficient funds");
        assert!(decoded.s2c.is_none());
    }
}
