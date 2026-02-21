// Hand-written prost structs for Trd_GetOrderFee (proto_id 2225).
// Tags match official Futu proto: Trd_GetOrderFee.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(string, repeated, tag = "2")]
    pub order_id_ex_list: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, repeated, tag = "2")]
    pub order_fee_list: ::prost::alloc::vec::Vec<super::trd_common::OrderFee>,
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
