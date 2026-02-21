// Hand-written prost structs for Qot_GetReference (proto_id 3206).
// Tags match official Futu proto: Qot_GetReference.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(int32, required, tag = "2")]
    pub reference_type: i32,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    /// NOTE: tag=2, not tag=1
    #[prost(message, repeated, tag = "2")]
    pub static_info_list: ::prost::alloc::vec::Vec<
        super::qot_common::SecurityStaticInfo,
    >,
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
