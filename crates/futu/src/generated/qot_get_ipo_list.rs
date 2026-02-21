// Hand-written prost structs for Qot_GetIpoList (proto_id 3217).
// Tags match official Futu proto: Qot_GetIpoList.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BasicIpoData {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(string, required, tag = "2")]
    pub name: ::prost::alloc::string::String,
    #[prost(string, optional, tag = "3")]
    pub list_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "4")]
    pub list_timestamp: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct WinningNumData {
    #[prost(string, required, tag = "1")]
    pub winning_name: ::prost::alloc::string::String,
    #[prost(string, required, tag = "2")]
    pub winning_info: ::prost::alloc::string::String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CnIpoExData {
    #[prost(string, required, tag = "1")]
    pub apply_code: ::prost::alloc::string::String,
    #[prost(int64, required, tag = "2")]
    pub issue_size: i64,
    #[prost(int64, required, tag = "3")]
    pub online_issue_size: i64,
    #[prost(int64, required, tag = "4")]
    pub apply_upper_limit: i64,
    #[prost(int64, required, tag = "5")]
    pub apply_limit_market_value: i64,
    #[prost(bool, required, tag = "6")]
    pub is_estimate_ipo_price: bool,
    #[prost(double, required, tag = "7")]
    pub ipo_price: f64,
    #[prost(double, required, tag = "8")]
    pub industry_pe_rate: f64,
    #[prost(bool, required, tag = "9")]
    pub is_estimate_winning_ratio: bool,
    #[prost(double, required, tag = "10")]
    pub winning_ratio: f64,
    #[prost(double, required, tag = "11")]
    pub issue_pe_rate: f64,
    #[prost(string, optional, tag = "12")]
    pub apply_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "13")]
    pub apply_timestamp: ::core::option::Option<f64>,
    #[prost(string, optional, tag = "14")]
    pub winning_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "15")]
    pub winning_timestamp: ::core::option::Option<f64>,
    #[prost(bool, required, tag = "16")]
    pub is_has_won: bool,
    #[prost(message, repeated, tag = "17")]
    pub winning_num_data: ::prost::alloc::vec::Vec<WinningNumData>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HkIpoExData {
    #[prost(double, required, tag = "1")]
    pub ipo_price_min: f64,
    #[prost(double, required, tag = "2")]
    pub ipo_price_max: f64,
    #[prost(double, required, tag = "3")]
    pub list_price: f64,
    #[prost(int32, required, tag = "4")]
    pub lot_size: i32,
    #[prost(double, required, tag = "5")]
    pub entrance_price: f64,
    #[prost(bool, required, tag = "6")]
    pub is_subscribe_status: bool,
    #[prost(string, optional, tag = "7")]
    pub apply_end_time: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(double, optional, tag = "8")]
    pub apply_end_timestamp: ::core::option::Option<f64>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct UsIpoExData {
    #[prost(double, required, tag = "1")]
    pub ipo_price_min: f64,
    #[prost(double, required, tag = "2")]
    pub ipo_price_max: f64,
    #[prost(int64, required, tag = "3")]
    pub issue_size: i64,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct IpoData {
    #[prost(message, required, tag = "1")]
    pub basic: BasicIpoData,
    #[prost(message, optional, tag = "2")]
    pub cn_ex_data: ::core::option::Option<CnIpoExData>,
    #[prost(message, optional, tag = "3")]
    pub hk_ex_data: ::core::option::Option<HkIpoExData>,
    #[prost(message, optional, tag = "4")]
    pub us_ex_data: ::core::option::Option<UsIpoExData>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(int32, required, tag = "1")]
    pub market: i32,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub ipo_list: ::prost::alloc::vec::Vec<IpoData>,
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
