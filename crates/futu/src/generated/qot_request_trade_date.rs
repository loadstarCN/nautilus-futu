// Hand-written prost structs for Qot_RequestTradeDate (proto_id 3219).
// Tags match official Futu proto: Qot_RequestTradeDate.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TradeDate {
    #[prost(string, required, tag = "1")]
    pub time: ::prost::alloc::string::String,
    #[prost(double, optional, tag = "2")]
    pub timestamp: ::core::option::Option<f64>,
    #[prost(int32, optional, tag = "3")]
    pub trade_date_type: ::core::option::Option<i32>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(int32, required, tag = "1")]
    pub market: i32,
    #[prost(string, required, tag = "2")]
    pub begin_time: ::prost::alloc::string::String,
    #[prost(string, required, tag = "3")]
    pub end_time: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "4")]
    pub security: ::core::option::Option<super::qot_common::Security>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub trade_date_list: ::prost::alloc::vec::Vec<TradeDate>,
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
