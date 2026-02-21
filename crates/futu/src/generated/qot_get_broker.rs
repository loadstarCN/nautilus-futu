// Hand-written prost structs for Qot_GetBroker (proto_id 3014).
// Tags match official Futu proto: Qot_GetBroker.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(message, repeated, tag = "2")]
    pub broker_ask_list: ::prost::alloc::vec::Vec<super::qot_common::Broker>,
    #[prost(message, repeated, tag = "3")]
    pub broker_bid_list: ::prost::alloc::vec::Vec<super::qot_common::Broker>,
    #[prost(string, optional, tag = "4")]
    pub name: ::core::option::Option<::prost::alloc::string::String>,
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
