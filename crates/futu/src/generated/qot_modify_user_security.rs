// Hand-written prost structs for Qot_ModifyUserSecurity.
// Tags match official Futu proto: Qot_ModifyUserSecurity.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(string, required, tag = "1")]
    pub group_name: ::prost::alloc::string::String,
    #[prost(int32, required, tag = "2")]
    pub op: i32,
    #[prost(message, repeated, tag = "3")]
    pub security_list: ::prost::alloc::vec::Vec<super::qot_common::Security>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {}

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
