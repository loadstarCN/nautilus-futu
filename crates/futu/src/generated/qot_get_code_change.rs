// Hand-written prost structs for Qot_GetCodeChange (proto_id 3216).
// Tags match official Futu proto: Qot_GetCodeChange.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CodeChangeInfo {
    #[prost(int32, required, tag = "1")]
    pub r#type: i32,
    #[prost(message, required, tag = "2")]
    pub security: super::qot_common::Security,
    #[prost(message, required, tag = "3")]
    pub related_security: super::qot_common::Security,
    #[prost(string, optional, tag = "4")]
    pub public_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "5")]
    pub public_timestamp: ::core::option::Option<f64>,
    #[prost(string, optional, tag = "6")]
    pub effective_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "7")]
    pub effective_timestamp: ::core::option::Option<f64>,
    #[prost(string, optional, tag = "8")]
    pub end_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "9")]
    pub end_timestamp: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TimeFilter {
    #[prost(int32, required, tag = "1")]
    pub r#type: i32,
    #[prost(string, optional, tag = "2")]
    pub begin_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(string, optional, tag = "3")]
    pub end_time: ::core::option::Option<::prost::alloc::string::String>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(int32, optional, tag = "1")]
    pub place_holder: ::core::option::Option<i32>,
    #[prost(message, repeated, tag = "2")]
    pub security_list: ::prost::alloc::vec::Vec<super::qot_common::Security>,
    #[prost(message, repeated, tag = "3")]
    pub time_filter_list: ::prost::alloc::vec::Vec<TimeFilter>,
    #[prost(int32, repeated, packed = "false", tag = "4")]
    pub type_list: ::prost::alloc::vec::Vec<i32>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub code_change_list: ::prost::alloc::vec::Vec<CodeChangeInfo>,
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
