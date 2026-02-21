// Hand-written prost structs for Qot_GetWarrant (proto_id 3213).
// Tags match official Futu proto: Qot_GetWarrant.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct WarrantData {
    #[prost(message, required, tag = "1")]
    pub stock: super::qot_common::Security,
    #[prost(message, required, tag = "2")]
    pub owner: super::qot_common::Security,
    #[prost(int32, required, tag = "3")]
    pub r#type: i32,
    #[prost(int32, required, tag = "4")]
    pub issuer: i32,
    #[prost(string, required, tag = "5")]
    pub maturity_time: ::prost::alloc::string::String,
    #[prost(double, optional, tag = "6")]
    pub maturity_timestamp: ::core::option::Option<f64>,
    #[prost(string, required, tag = "7")]
    pub list_time: ::prost::alloc::string::String,
    #[prost(double, optional, tag = "8")]
    pub list_timestamp: ::core::option::Option<f64>,
    #[prost(string, required, tag = "9")]
    pub last_trade_time: ::prost::alloc::string::String,
    #[prost(double, optional, tag = "10")]
    pub last_trade_timestamp: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "11")]
    pub recovery_price: ::core::option::Option<f64>,
    #[prost(double, required, tag = "12")]
    pub conversion_ratio: f64,
    #[prost(int32, required, tag = "13")]
    pub lot_size: i32,
    #[prost(double, required, tag = "14")]
    pub strike_price: f64,
    #[prost(double, required, tag = "15")]
    pub last_close_price: f64,
    #[prost(string, required, tag = "16")]
    pub name: ::prost::alloc::string::String,
    #[prost(double, required, tag = "17")]
    pub cur_price: f64,
    #[prost(double, required, tag = "18")]
    pub price_change_val: f64,
    #[prost(double, required, tag = "19")]
    pub change_rate: f64,
    #[prost(int32, required, tag = "20")]
    pub status: i32,
    #[prost(double, required, tag = "21")]
    pub bid_price: f64,
    #[prost(double, required, tag = "22")]
    pub ask_price: f64,
    #[prost(int64, required, tag = "23")]
    pub bid_vol: i64,
    #[prost(int64, required, tag = "24")]
    pub ask_vol: i64,
    #[prost(int64, required, tag = "25")]
    pub volume: i64,
    #[prost(double, required, tag = "26")]
    pub turnover: f64,
    #[prost(double, required, tag = "27")]
    pub score: f64,
    #[prost(double, required, tag = "28")]
    pub premium: f64,
    #[prost(double, required, tag = "29")]
    pub break_even_point: f64,
    #[prost(double, required, tag = "30")]
    pub leverage: f64,
    #[prost(double, required, tag = "31")]
    pub ipop: f64,
    #[prost(double, optional, tag = "32")]
    pub price_recovery_ratio: ::core::option::Option<f64>,
    #[prost(double, required, tag = "33")]
    pub conversion_price: f64,
    #[prost(double, required, tag = "34")]
    pub street_rate: f64,
    #[prost(int64, required, tag = "35")]
    pub street_vol: i64,
    #[prost(double, required, tag = "36")]
    pub amplitude: f64,
    #[prost(int64, required, tag = "37")]
    pub issue_size: i64,
    // NOTE: There is no tag=38
    #[prost(double, required, tag = "39")]
    pub high_price: f64,
    #[prost(double, required, tag = "40")]
    pub low_price: f64,
    #[prost(double, optional, tag = "41")]
    pub implied_volatility: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "42")]
    pub delta: ::core::option::Option<f64>,
    #[prost(double, required, tag = "43")]
    pub effective_leverage: f64,
    #[prost(double, optional, tag = "44")]
    pub upper_strike_price: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "45")]
    pub lower_strike_price: ::core::option::Option<f64>,
    #[prost(int32, optional, tag = "46")]
    pub in_line_price_status: ::core::option::Option<i32>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(int32, required, tag = "1")]
    pub begin: i32,
    #[prost(int32, required, tag = "2")]
    pub num: i32,
    #[prost(int32, required, tag = "3")]
    pub sort_field: i32,
    #[prost(bool, required, tag = "4")]
    pub ascend: bool,
    #[prost(message, optional, tag = "5")]
    pub owner: ::core::option::Option<super::qot_common::Security>,
    #[prost(int32, repeated, packed = "false", tag = "6")]
    pub type_list: ::prost::alloc::vec::Vec<i32>,
    #[prost(int32, repeated, packed = "false", tag = "7")]
    pub issuer_list: ::prost::alloc::vec::Vec<i32>,
    #[prost(string, optional, tag = "8")]
    pub maturity_time_min: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(string, optional, tag = "9")]
    pub maturity_time_max: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(int32, optional, tag = "10")]
    pub ipo_period: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "11")]
    pub price_type: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "12")]
    pub status: ::core::option::Option<i32>,
    #[prost(double, optional, tag = "13")]
    pub cur_price_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "14")]
    pub cur_price_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "15")]
    pub strike_price_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "16")]
    pub strike_price_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "17")]
    pub street_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "18")]
    pub street_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "19")]
    pub conversion_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "20")]
    pub conversion_max: ::core::option::Option<f64>,
    #[prost(uint64, optional, tag = "21")]
    pub vol_min: ::core::option::Option<u64>,
    #[prost(uint64, optional, tag = "22")]
    pub vol_max: ::core::option::Option<u64>,
    #[prost(double, optional, tag = "23")]
    pub premium_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "24")]
    pub premium_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "25")]
    pub leverage_ratio_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "26")]
    pub leverage_ratio_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "27")]
    pub delta_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "28")]
    pub delta_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "29")]
    pub implied_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "30")]
    pub implied_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "31")]
    pub recovery_price_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "32")]
    pub recovery_price_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "33")]
    pub price_recovery_ratio_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "34")]
    pub price_recovery_ratio_max: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(bool, required, tag = "1")]
    pub last_page: bool,
    #[prost(int32, required, tag = "2")]
    pub all_count: i32,
    #[prost(message, repeated, tag = "3")]
    pub warrant_data_list: ::prost::alloc::vec::Vec<WarrantData>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Request {
    #[prost(message, required, tag = "1")]
    pub c2s: C2s,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Response {
    #[prost(int32, required, tag = "1", default = "-400")]
    pub ret_type: i32,
    #[prost(string, optional, tag = "2")]
    pub ret_msg: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(int32, optional, tag = "3")]
    pub err_code: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "4")]
    pub s2c: ::core::option::Option<S2c>,
}
