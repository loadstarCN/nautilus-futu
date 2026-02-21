// Hand-written prost structs for Qot_GetPlateSecurity (proto_id 3205).
// Tags match official Futu proto: Qot_GetPlateSecurity.proto

/// C2S request.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    /// Plate security (required)
    #[prost(message, required, tag = "1")]
    pub plate: super::qot_common::Security,
    /// SortField, sort field (optional)
    #[prost(int32, optional, tag = "2")]
    pub sort_field: ::core::option::Option<i32>,
    /// Ascending order (optional, default depends on sort field)
    #[prost(bool, optional, tag = "3")]
    pub ascend: ::core::option::Option<bool>,
}

/// S2C response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    /// Static info list for securities in the plate
    #[prost(message, repeated, tag = "1")]
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
