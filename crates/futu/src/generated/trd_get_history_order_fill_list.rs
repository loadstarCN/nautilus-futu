// Hand-written prost structs for Trd_GetHistoryOrderFillList (proto_id 2222).
// Tags match official Futu proto: Trd_GetHistoryOrderFillList.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, required, tag = "2")]
    pub filter_conditions: super::trd_common::TrdFilterConditions,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, repeated, tag = "2")]
    pub order_fill_list: ::prost::alloc::vec::Vec<super::trd_common::OrderFill>,
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
