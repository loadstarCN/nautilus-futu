// Hand-written prost structs for Trd_GetMarginRatio (proto_id 2223).
// Tags match official Futu proto: Trd_GetMarginRatio.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MarginRatioInfo {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(bool, optional, tag = "2")]
    pub is_long_permit: ::core::option::Option<bool>,
    #[prost(bool, optional, tag = "3")]
    pub is_short_permit: ::core::option::Option<bool>,
    #[prost(double, optional, tag = "4")]
    pub short_pool_remain: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "5")]
    pub short_fee_rate: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "6")]
    pub alert_long_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "7")]
    pub alert_short_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "8")]
    pub im_long_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "9")]
    pub im_short_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "10")]
    pub mcm_long_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "11")]
    pub mcm_short_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "12")]
    pub mm_long_ratio: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "13")]
    pub mm_short_ratio: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, repeated, tag = "2")]
    pub security_list: ::prost::alloc::vec::Vec<super::qot_common::Security>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, required, tag = "1")]
    pub header: super::trd_common::TrdHeader,
    #[prost(message, repeated, tag = "2")]
    pub margin_ratio_info_list: ::prost::alloc::vec::Vec<MarginRatioInfo>,
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
