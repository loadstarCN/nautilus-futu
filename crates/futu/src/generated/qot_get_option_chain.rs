// Hand-written prost structs for Qot_GetOptionChain (proto_id 3209).
// Tags match official Futu proto: Qot_GetOptionChain.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct DataFilter {
    #[prost(double, optional, tag = "1")]
    pub implied_volatility_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "2")]
    pub implied_volatility_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "3")]
    pub delta_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "4")]
    pub delta_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "5")]
    pub gamma_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "6")]
    pub gamma_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "7")]
    pub vega_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "8")]
    pub vega_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "9")]
    pub theta_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "10")]
    pub theta_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "11")]
    pub rho_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "12")]
    pub rho_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "13")]
    pub net_open_interest_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "14")]
    pub net_open_interest_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "15")]
    pub open_interest_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "16")]
    pub open_interest_max: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "17")]
    pub vol_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "18")]
    pub vol_max: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OptionItem {
    #[prost(message, optional, tag = "1")]
    pub call: ::core::option::Option<super::qot_common::SecurityStaticInfo>,
    #[prost(message, optional, tag = "2")]
    pub put: ::core::option::Option<super::qot_common::SecurityStaticInfo>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OptionChain {
    #[prost(string, required, tag = "1")]
    pub strike_time: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "2")]
    pub option: ::prost::alloc::vec::Vec<OptionItem>,
    #[prost(double, optional, tag = "3")]
    pub strike_timestamp: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(message, required, tag = "1")]
    pub owner: super::qot_common::Security,
    #[prost(int32, optional, tag = "2")]
    pub r#type: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "3")]
    pub condition: ::core::option::Option<i32>,
    #[prost(string, required, tag = "4")]
    pub begin_time: ::prost::alloc::string::String,
    #[prost(string, required, tag = "5")]
    pub end_time: ::prost::alloc::string::String,
    #[prost(int32, optional, tag = "6")]
    pub index_option_type: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "7")]
    pub data_filter: ::core::option::Option<DataFilter>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub option_chain: ::prost::alloc::vec::Vec<OptionChain>,
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
