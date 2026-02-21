// Hand-written prost structs for Qot_GetCapitalFlow (proto_id 3211).
// Tags match official Futu proto: Qot_GetCapitalFlow.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CapitalFlowItem {
    #[prost(double, required, tag = "1")]
    pub in_flow: f64,
    #[prost(string, optional, tag = "2")]
    pub time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "3")]
    pub timestamp: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "4")]
    pub main_in_flow: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "5")]
    pub super_in_flow: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "6")]
    pub big_in_flow: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "7")]
    pub mid_in_flow: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "8")]
    pub sml_in_flow: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(int32, optional, tag = "2")]
    pub period_type: ::core::option::Option<i32>,
    #[prost(string, optional, tag = "3")]
    pub begin_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(string, optional, tag = "4")]
    pub end_time: ::core::option::Option<::prost::alloc::string::String>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub flow_item_list: ::prost::alloc::vec::Vec<CapitalFlowItem>,
    #[prost(string, optional, tag = "2")]
    pub last_valid_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "3")]
    pub last_valid_timestamp: ::core::option::Option<f64>,
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
