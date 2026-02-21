// Hand-written prost structs for Qot_GetFutureInfo (proto_id 3218).
// Tags match official Futu proto: Qot_GetFutureInfo.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TradeTime {
    #[prost(double, optional, tag = "1")]
    pub begin: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "2")]
    pub end: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FutureInfo {
    #[prost(string, required, tag = "1")]
    pub name: ::prost::alloc::string::String,
    #[prost(message, required, tag = "2")]
    pub security: super::qot_common::Security,
    #[prost(string, required, tag = "3")]
    pub last_trade_time: ::prost::alloc::string::String,
    #[prost(double, optional, tag = "4")]
    pub last_trade_timestamp: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "5")]
    pub owner: ::core::option::Option<super::qot_common::Security>,
    #[prost(string, required, tag = "6")]
    pub owner_other: ::prost::alloc::string::String,
    #[prost(string, required, tag = "7")]
    pub exchange: ::prost::alloc::string::String,
    #[prost(string, required, tag = "8")]
    pub contract_type: ::prost::alloc::string::String,
    #[prost(double, required, tag = "9")]
    pub contract_size: f64,
    #[prost(string, required, tag = "10")]
    pub contract_size_unit: ::prost::alloc::string::String,
    #[prost(string, required, tag = "11")]
    pub quote_currency: ::prost::alloc::string::String,
    #[prost(double, required, tag = "12")]
    pub min_var: f64,
    #[prost(string, required, tag = "13")]
    pub min_var_unit: ::prost::alloc::string::String,
    #[prost(string, optional, tag = "14")]
    pub quote_unit: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, repeated, tag = "15")]
    pub trade_time: ::prost::alloc::vec::Vec<TradeTime>,
    #[prost(string, required, tag = "16")]
    pub time_zone: ::prost::alloc::string::String,
    #[prost(string, required, tag = "17")]
    pub exchange_format_url: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "18")]
    pub origin: ::core::option::Option<super::qot_common::Security>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, repeated, tag = "1")]
    pub security_list: ::prost::alloc::vec::Vec<super::qot_common::Security>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub future_info_list: ::prost::alloc::vec::Vec<FutureInfo>,
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
