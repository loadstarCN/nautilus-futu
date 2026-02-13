// Hand-written prost structs for GetGlobalState (proto 1002).
// Futu API: https://openapi.futunn.com/futu-api-doc/tcp/intro.html

#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(uint64, required, tag = "1")]
    pub user_id: u64,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(int32, required, tag = "1")]
    pub market_hk: i32,
    #[prost(int32, required, tag = "2")]
    pub market_us: i32,
    #[prost(int32, required, tag = "3")]
    pub market_cn: i32,
    #[prost(int32, optional, tag = "4")]
    pub market_hk_future: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub market_us_future: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub market_sg: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "7")]
    pub market_jp: ::core::option::Option<i32>,
    #[prost(bool, required, tag = "8")]
    pub qot_logined: bool,
    #[prost(bool, required, tag = "9")]
    pub trd_logined: bool,
    #[prost(int32, optional, tag = "10")]
    pub server_ver: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "11")]
    pub server_build_no: ::core::option::Option<i32>,
    #[prost(int64, optional, tag = "12")]
    pub time: ::core::option::Option<i64>,
    #[prost(double, optional, tag = "13")]
    pub local_time: ::core::option::Option<f64>,
}

#[derive(Clone, Copy, PartialEq, ::prost::Message)]
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
