// Hand-written prost structs for Trd_GetMaxTrdQtys (proto_id 2111).
// Tags match official Futu proto: Trd_GetMaxTrdQtys.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(int32, required, tag = "2")]
    pub order_type: i32,
    #[prost(string, required, tag = "3")]
    pub code: ::prost::alloc::string::String,
    #[prost(double, required, tag = "4")]
    pub price: f64,
    #[prost(uint64, optional, tag = "5")]
    pub order_id: ::core::option::Option<u64>,
    #[prost(bool, optional, tag = "6")]
    pub adjust_price: ::core::option::Option<bool>,
    #[prost(double, optional, tag = "7")]
    pub adjust_side_and_limit: ::core::option::Option<f64>,
    #[prost(int32, optional, tag = "8")]
    pub sec_market: ::core::option::Option<i32>,
    #[prost(string, optional, tag = "9")]
    pub order_id_ex: ::core::option::Option<::prost::alloc::string::String>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, optional, tag = "2")]
    pub max_trd_qtys: ::core::option::Option<super::trd_common::MaxTrdQtys>,
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
