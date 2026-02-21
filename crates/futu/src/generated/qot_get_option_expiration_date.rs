// Hand-written prost structs for Qot_GetOptionExpirationDate (proto_id 3210).
// Tags match official Futu proto: Qot_GetOptionExpirationDate.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OptionExpirationDate {
    #[prost(string, optional, tag = "1")]
    pub strike_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "2")]
    pub strike_timestamp: ::core::option::Option<f64>,
    #[prost(int32, required, tag = "3")]
    pub option_expiry_date_distance: i32,
    #[prost(int32, optional, tag = "4")]
    pub cycle: ::core::option::Option<i32>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub owner: super::qot_common::Security,
    #[prost(int32, optional, tag = "2")]
    pub index_option_type: ::core::option::Option<i32>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub date_list: ::prost::alloc::vec::Vec<OptionExpirationDate>,
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
