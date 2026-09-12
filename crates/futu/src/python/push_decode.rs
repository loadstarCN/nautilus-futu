//! Decode Futu push messages into Python dicts.

use prost::Message;
use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::{PyDict, PyList};

// Proto IDs for push notifications
pub const PROTO_QOT_UPDATE_BASIC_QOT: u32 = 3005;
pub const PROTO_QOT_UPDATE_TICKER: u32 = 3011;
pub const PROTO_QOT_UPDATE_ORDER_BOOK: u32 = 3013;
pub const PROTO_QOT_UPDATE_KL: u32 = 3007;
pub const PROTO_TRD_UPDATE_ORDER: u32 = 2208;
pub const PROTO_TRD_UPDATE_ORDER_FILL: u32 = 2218;
pub const PROTO_NOTIFY: u32 = 1003;

/// Decode a push message body into a Python object based on proto_id.
pub fn decode_push_message(py: Python<'_>, proto_id: u32, body: &[u8]) -> PyResult<PyObject> {
    match proto_id {
        PROTO_QOT_UPDATE_BASIC_QOT => decode_basic_qot(py, body),
        PROTO_QOT_UPDATE_TICKER => decode_ticker(py, body),
        PROTO_QOT_UPDATE_ORDER_BOOK => decode_order_book(py, body),
        PROTO_QOT_UPDATE_KL => decode_kl(py, body),
        PROTO_TRD_UPDATE_ORDER => decode_trd_order(py, body),
        PROTO_TRD_UPDATE_ORDER_FILL => decode_trd_fill(py, body),
        PROTO_NOTIFY => decode_notify(py, body),
        _ => Err(PyValueError::new_err(format!("Unknown push proto_id: {}", proto_id))),
    }
}

fn decode_basic_qot(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::qot_update_basic_qot::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in basic qot push"))?;

    let list = PyList::empty_bound(py);
    for qot in &s2c.basic_qot_list {
        let dict = PyDict::new_bound(py);
        dict.set_item("market", qot.security.market)?;
        dict.set_item("code", &qot.security.code)?;
        dict.set_item("name", &qot.name)?;
        dict.set_item("is_suspended", qot.is_suspended)?;
        dict.set_item("cur_price", qot.cur_price)?;
        dict.set_item("price_spread", qot.price_spread)?;
        dict.set_item("volume", qot.volume)?;
        dict.set_item("high_price", qot.high_price)?;
        dict.set_item("open_price", qot.open_price)?;
        dict.set_item("low_price", qot.low_price)?;
        dict.set_item("last_close_price", qot.last_close_price)?;
        dict.set_item("turnover", qot.turnover)?;
        dict.set_item("turnover_rate", qot.turnover_rate)?;
        dict.set_item("amplitude", qot.amplitude)?;
        dict.set_item("update_timestamp", qot.update_timestamp)?;
        list.append(dict)?;
    }
    Ok(list.into_any().unbind())
}

fn decode_ticker(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::qot_update_ticker::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in ticker push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("market", s2c.security.market)?;
    dict.set_item("code", &s2c.security.code)?;

    let tickers = PyList::empty_bound(py);
    for t in &s2c.ticker_list {
        let td = PyDict::new_bound(py);
        td.set_item("price", t.price)?;
        td.set_item("volume", t.volume)?;
        td.set_item("dir", t.dir)?;
        td.set_item("sequence", t.sequence)?;
        td.set_item("timestamp", t.timestamp)?;
        td.set_item("turnover", t.turnover)?;
        tickers.append(td)?;
    }
    dict.set_item("tickers", tickers)?;
    Ok(dict.into_any().unbind())
}

fn decode_order_book(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::qot_update_order_book::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in order book push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("market", s2c.security.market)?;
    dict.set_item("code", &s2c.security.code)?;

    let asks = PyList::empty_bound(py);
    for ob in &s2c.order_book_ask_list {
        let d = PyDict::new_bound(py);
        d.set_item("price", ob.price)?;
        d.set_item("volume", ob.volume)?;
        d.set_item("order_count", ob.order_count)?;
        asks.append(d)?;
    }
    dict.set_item("asks", asks)?;

    let bids = PyList::empty_bound(py);
    for ob in &s2c.order_book_bid_list {
        let d = PyDict::new_bound(py);
        d.set_item("price", ob.price)?;
        d.set_item("volume", ob.volume)?;
        d.set_item("order_count", ob.order_count)?;
        bids.append(d)?;
    }
    dict.set_item("bids", bids)?;
    dict.set_item("svr_recv_time_bid_timestamp", s2c.svr_recv_time_bid_timestamp)?;
    dict.set_item("svr_recv_time_ask_timestamp", s2c.svr_recv_time_ask_timestamp)?;
    Ok(dict.into_any().unbind())
}

fn decode_kl(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::qot_update_kl::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in KL push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("market", s2c.security.market)?;
    dict.set_item("code", &s2c.security.code)?;
    dict.set_item("kl_type", s2c.kl_type)?;
    dict.set_item("rehab_type", s2c.rehab_type)?;

    let kl_list = PyList::empty_bound(py);
    for kl in &s2c.kl_list {
        let d = PyDict::new_bound(py);
        d.set_item("open_price", kl.open_price)?;
        d.set_item("high_price", kl.high_price)?;
        d.set_item("low_price", kl.low_price)?;
        d.set_item("close_price", kl.close_price)?;
        d.set_item("last_close_price", kl.last_close_price)?;
        d.set_item("volume", kl.volume)?;
        d.set_item("turnover", kl.turnover)?;
        d.set_item("change_rate", kl.change_rate)?;
        d.set_item("timestamp", kl.timestamp)?;
        d.set_item("is_blank", kl.is_blank)?;
        kl_list.append(d)?;
    }
    dict.set_item("kl_list", kl_list)?;
    Ok(dict.into_any().unbind())
}

fn decode_trd_order(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::trd_update_order::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in order push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("trd_env", s2c.header.trd_env)?;
    dict.set_item("acc_id", s2c.header.acc_id)?;

    let o = &s2c.order;
    let order_dict = PyDict::new_bound(py);
    order_dict.set_item("trd_side", o.trd_side)?;
    order_dict.set_item("order_type", o.order_type)?;
    order_dict.set_item("order_status", o.order_status)?;
    order_dict.set_item("order_id", o.order_id)?;
    order_dict.set_item("order_id_ex", &o.order_id_ex)?;
    order_dict.set_item("code", &o.code)?;
    order_dict.set_item("name", &o.name)?;
    order_dict.set_item("qty", o.qty)?;
    order_dict.set_item("price", o.price)?;
    order_dict.set_item("fill_qty", o.fill_qty)?;
    order_dict.set_item("fill_avg_price", o.fill_avg_price)?;
    order_dict.set_item("sec_market", o.sec_market)?;
    order_dict.set_item("create_timestamp", o.create_timestamp)?;
    order_dict.set_item("update_timestamp", o.update_timestamp)?;
    order_dict.set_item("time_in_force", o.time_in_force)?;
    order_dict.set_item("remark", &o.remark)?;
    order_dict.set_item("last_err_msg", &o.last_err_msg)?;
    order_dict.set_item("fill_outside_rth", o.fill_outside_rth)?;
    order_dict.set_item("aux_price", o.aux_price)?;
    order_dict.set_item("trail_type", o.trail_type)?;
    order_dict.set_item("trail_value", o.trail_value)?;
    order_dict.set_item("trail_spread", o.trail_spread)?;
    order_dict.set_item("currency", o.currency)?;
    dict.set_item("order", order_dict)?;
    Ok(dict.into_any().unbind())
}

fn decode_trd_fill(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    let resp = crate::generated::trd_update_order_fill::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in fill push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("trd_env", s2c.header.trd_env)?;
    dict.set_item("acc_id", s2c.header.acc_id)?;

    let f = &s2c.order_fill;
    let fill_dict = PyDict::new_bound(py);
    fill_dict.set_item("trd_side", f.trd_side)?;
    fill_dict.set_item("fill_id", f.fill_id)?;
    fill_dict.set_item("fill_id_ex", &f.fill_id_ex)?;
    fill_dict.set_item("order_id", f.order_id)?;
    fill_dict.set_item("order_id_ex", &f.order_id_ex)?;
    fill_dict.set_item("code", &f.code)?;
    fill_dict.set_item("name", &f.name)?;
    fill_dict.set_item("qty", f.qty)?;
    fill_dict.set_item("price", f.price)?;
    fill_dict.set_item("sec_market", f.sec_market)?;
    fill_dict.set_item("create_timestamp", f.create_timestamp)?;
    fill_dict.set_item("counter_broker_id", f.counter_broker_id.unwrap_or_default())?;
    fill_dict.set_item("counter_broker_name", f.counter_broker_name.clone().unwrap_or_default())?;
    fill_dict.set_item("update_timestamp", f.update_timestamp.unwrap_or(0.0))?;
    fill_dict.set_item("status", f.status)?;
    dict.set_item("fill", fill_dict)?;
    Ok(dict.into_any().unbind())
}

/// Decode an OpenD `Notify` (1003) push: gateway events, connection status,
/// quota changes.  Every sub-message is optional, so the returned dict only
/// contains the section matching `type`.
fn decode_notify(py: Python<'_>, body: &[u8]) -> PyResult<PyObject> {
    use crate::generated::notify as n;
    let resp = n::Response::decode(body)
        .map_err(|e| PyValueError::new_err(format!("Decode error: {}", e)))?;

    let s2c = resp.s2c
        .ok_or_else(|| PyValueError::new_err("Missing s2c in notify push"))?;

    let dict = PyDict::new_bound(py);
    dict.set_item("type", s2c.r#type)?;
    let type_name = match s2c.r#type {
        n::NOTIFY_TYPE_GTW_EVENT => "gtw_event",
        n::NOTIFY_TYPE_PROGRAM_STATUS => "program_status",
        n::NOTIFY_TYPE_CONN_STATUS => "conn_status",
        n::NOTIFY_TYPE_QOT_RIGHT => "qot_right",
        n::NOTIFY_TYPE_API_LEVEL => "api_level",
        n::NOTIFY_TYPE_API_QUOTA => "api_quota",
        n::NOTIFY_TYPE_USED_QUOTA => "used_quota",
        _ => "unknown",
    };
    dict.set_item("type_name", type_name)?;

    if let Some(ev) = s2c.event {
        let d = PyDict::new_bound(py);
        d.set_item("event_type", ev.event_type)?;
        d.set_item("desc", ev.desc.as_deref())?;
        dict.set_item("event", d)?;
    }
    if let Some(ps) = s2c.program_status.and_then(|p| p.program_status) {
        let d = PyDict::new_bound(py);
        d.set_item("type", ps.r#type)?;
        d.set_item("desc", ps.str_ext_desc.as_deref())?;
        dict.set_item("program_status", d)?;
    }
    if let Some(cs) = s2c.connect_status {
        let d = PyDict::new_bound(py);
        d.set_item("qot_logined", cs.qot_logined)?;
        d.set_item("trd_logined", cs.trd_logined)?;
        dict.set_item("connect_status", d)?;
    }
    if let Some(qr) = s2c.qot_right {
        let d = PyDict::new_bound(py);
        d.set_item("hk_qot_right", qr.hk_qot_right)?;
        d.set_item("us_qot_right", qr.us_qot_right)?;
        d.set_item("cn_qot_right", qr.cn_qot_right)?;
        d.set_item("hk_option_qot_right", qr.hk_option_qot_right)?;
        d.set_item("has_us_option_qot_right", qr.has_us_option_qot_right)?;
        d.set_item("hk_future_qot_right", qr.hk_future_qot_right)?;
        d.set_item("us_future_qot_right", qr.us_future_qot_right)?;
        d.set_item("sg_future_qot_right", qr.sg_future_qot_right)?;
        d.set_item("jp_future_qot_right", qr.jp_future_qot_right)?;
        dict.set_item("qot_right", d)?;
    }
    if let Some(al) = s2c.api_level {
        dict.set_item("api_level", al.api_level.as_deref())?;
    }
    if let Some(q) = s2c.api_quota {
        let d = PyDict::new_bound(py);
        d.set_item("sub_quota", q.sub_quota)?;
        d.set_item("history_kl_quota", q.history_kl_quota)?;
        dict.set_item("api_quota", d)?;
    }
    if let Some(u) = s2c.used_quota {
        let d = PyDict::new_bound(py);
        d.set_item("used_sub_quota", u.used_sub_quota)?;
        d.set_item("used_kline_quota", u.used_kline_quota)?;
        dict.set_item("used_quota", d)?;
    }
    Ok(dict.into_any().unbind())
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constants() {
        assert_eq!(PROTO_QOT_UPDATE_BASIC_QOT, 3005);
        assert_eq!(PROTO_QOT_UPDATE_TICKER, 3011);
        assert_eq!(PROTO_QOT_UPDATE_ORDER_BOOK, 3013);
        assert_eq!(PROTO_QOT_UPDATE_KL, 3007);
        assert_eq!(PROTO_TRD_UPDATE_ORDER, 2208);
        assert_eq!(PROTO_TRD_UPDATE_ORDER_FILL, 2218);
    }

    #[test]
    fn test_basic_qot_roundtrip() {
        let s2c = crate::generated::qot_update_basic_qot::S2c {
            basic_qot_list: vec![crate::generated::qot_common::BasicQot {
                security: crate::generated::qot_common::Security {
                    market: 1,
                    code: "00700".to_string(),
                },
                name: Some("腾讯控股".to_string()),
                is_suspended: false,
                list_time: "2004-06-16".to_string(),
                price_spread: 0.2,
                update_time: "2024-01-01 10:00:00".to_string(),
                high_price: 350.0,
                open_price: 340.0,
                low_price: 335.0,
                cur_price: 345.0,
                last_close_price: 342.0,
                volume: 10000000,
                turnover: 3400000000.0,
                update_timestamp: Some(1704067200.0),
                ..Default::default()
            }],
        };
        let resp = crate::generated::qot_update_basic_qot::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();

        // Verify it decodes back correctly
        let decoded = crate::generated::qot_update_basic_qot::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.basic_qot_list.len(), 1);
        assert_eq!(s2c.basic_qot_list[0].security.code, "00700");
        assert_eq!(s2c.basic_qot_list[0].cur_price, 345.0);
    }

    #[test]
    fn test_ticker_roundtrip() {
        let s2c = crate::generated::qot_update_ticker::S2c {
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
        };
        let resp = crate::generated::qot_update_ticker::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();
        let decoded = crate::generated::qot_update_ticker::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.security.code, "AAPL");
        assert_eq!(s2c.ticker_list.len(), 1);
        assert_eq!(s2c.ticker_list[0].price, 195.5);
    }

    #[test]
    fn test_order_book_roundtrip() {
        let s2c = crate::generated::qot_update_order_book::S2c {
            security: crate::generated::qot_common::Security {
                market: 1,
                code: "00700".to_string(),
            },
            name: None,
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
        };
        let resp = crate::generated::qot_update_order_book::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();
        let decoded = crate::generated::qot_update_order_book::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.order_book_ask_list.len(), 1);
        assert_eq!(s2c.order_book_bid_list.len(), 1);
        assert_eq!(s2c.order_book_ask_list[0].price, 346.0);
    }

    #[test]
    fn test_kl_roundtrip() {
        let s2c = crate::generated::qot_update_kl::S2c {
            rehab_type: 1,
            kl_type: 1,
            security: crate::generated::qot_common::Security {
                market: 1,
                code: "00700".to_string(),
            },
            name: None,
            kl_list: vec![crate::generated::qot_common::KLine {
                time: "2024-01-01 10:00:00".to_string(),
                is_blank: false,
                high_price: Some(350.0),
                open_price: Some(340.0),
                low_price: Some(335.0),
                close_price: Some(345.0),
                volume: Some(10000),
                turnover: Some(3400000.0),
                timestamp: Some(1704067200.0),
                ..Default::default()
            }],
        };
        let resp = crate::generated::qot_update_kl::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();
        let decoded = crate::generated::qot_update_kl::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.kl_type, 1);
        assert_eq!(s2c.kl_list.len(), 1);
        assert_eq!(s2c.kl_list[0].close_price, Some(345.0));
    }

    #[test]
    fn test_trd_order_roundtrip() {
        let s2c = crate::generated::trd_update_order::S2c {
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 1,
                acc_id: 12345,
                trd_market: 1,
            },
            order: crate::generated::trd_common::Order {
                trd_side: 1,
                order_type: 1,
                order_status: 10,
                order_id: 999,
                order_id_ex: "EX999".to_string(),
                code: "00700".to_string(),
                name: "腾讯控股".to_string(),
                qty: 100.0,
                price: Some(345.0),
                create_time: "2024-01-01 10:00:00".to_string(),
                update_time: "2024-01-01 10:00:01".to_string(),
                fill_qty: Some(0.0),
                fill_avg_price: Some(0.0),
                sec_market: Some(1),
                create_timestamp: Some(1704067200.0),
                update_timestamp: Some(1704067201.0),
                time_in_force: Some(0),
                remark: Some("test".to_string()),
                ..Default::default()
            },
        };
        let resp = crate::generated::trd_update_order::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();
        let decoded = crate::generated::trd_update_order::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.header.acc_id, 12345);
        assert_eq!(s2c.order.order_id, 999);
        assert_eq!(s2c.order.order_status, 10);
    }

    #[test]
    fn test_trd_fill_roundtrip() {
        let s2c = crate::generated::trd_update_order_fill::S2c {
            header: crate::generated::trd_common::TrdHeader {
                trd_env: 1,
                acc_id: 12345,
                trd_market: 1,
            },
            order_fill: crate::generated::trd_common::OrderFill {
                trd_side: 1,
                fill_id: 555,
                fill_id_ex: "FEX555".to_string(),
                order_id: Some(999),
                order_id_ex: Some("EX999".to_string()),
                code: "00700".to_string(),
                name: "腾讯控股".to_string(),
                qty: 50.0,
                price: 345.0,
                create_time: "2024-01-01 10:00:05".to_string(),
                sec_market: Some(1),
                create_timestamp: Some(1704067205.0),
                counter_broker_id: Some(1234),
                counter_broker_name: Some("中银国际".to_string()),
                update_timestamp: Some(1704067210.0),
                ..Default::default()
            },
        };
        let resp = crate::generated::trd_update_order_fill::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(s2c),
        };
        let body = resp.encode_to_vec();
        let decoded = crate::generated::trd_update_order_fill::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.order_fill.fill_id, 555);
        assert_eq!(s2c.order_fill.qty, 50.0);
        assert_eq!(s2c.order_fill.counter_broker_id, Some(1234));
        assert_eq!(s2c.order_fill.counter_broker_name, Some("中银国际".to_string()));
        assert_eq!(s2c.order_fill.update_timestamp, Some(1704067210.0));
    }

    #[test]
    fn test_notify_roundtrip() {
        use crate::generated::notify as n;
        let s2c = n::S2c {
            r#type: n::NOTIFY_TYPE_CONN_STATUS,
            connect_status: Some(n::ConnectStatus { qot_logined: Some(true), trd_logined: Some(false) }),
            ..Default::default()
        };
        let resp = n::Response { ret_type: 0, ret_msg: None, err_code: None, s2c: Some(s2c) };
        let body = resp.encode_to_vec();
        let decoded = n::Response::decode(body.as_slice()).unwrap();
        let s2c = decoded.s2c.unwrap();
        assert_eq!(s2c.r#type, 3);
        assert_eq!(s2c.connect_status.unwrap().qot_logined, Some(true));
        assert!(s2c.event.is_none());
        assert_eq!(PROTO_NOTIFY, 1003);
    }

    #[test]
    fn test_invalid_body_errors() {
        let bad_body = b"this is not protobuf";

        // All decoders should fail gracefully on invalid data
        let result = crate::generated::qot_update_basic_qot::Response::decode(bad_body.as_slice());
        assert!(result.is_err());

        let result = crate::generated::qot_update_ticker::Response::decode(bad_body.as_slice());
        assert!(result.is_err());

        let result = crate::generated::qot_update_order_book::Response::decode(bad_body.as_slice());
        assert!(result.is_err());

        let result = crate::generated::trd_update_order::Response::decode(bad_body.as_slice());
        assert!(result.is_err());

        let result = crate::generated::trd_update_order_fill::Response::decode(bad_body.as_slice());
        assert!(result.is_err());
    }
}
