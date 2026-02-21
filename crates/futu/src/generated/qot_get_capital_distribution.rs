// Hand-written prost structs for Qot_GetCapitalDistribution (proto_id 3212).
// Tags match official Futu proto: Qot_GetCapitalDistribution.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(double, required, tag = "1")]
    pub capital_in_big: f64,
    #[prost(double, required, tag = "2")]
    pub capital_in_mid: f64,
    #[prost(double, required, tag = "3")]
    pub capital_in_small: f64,
    #[prost(double, required, tag = "4")]
    pub capital_out_big: f64,
    #[prost(double, required, tag = "5")]
    pub capital_out_mid: f64,
    #[prost(double, required, tag = "6")]
    pub capital_out_small: f64,
    #[prost(string, optional, tag = "7")]
    pub update_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "8")]
    pub update_timestamp: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "9")]
    pub capital_in_super: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "10")]
    pub capital_out_super: ::core::option::Option<f64>,
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
