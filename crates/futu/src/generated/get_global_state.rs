// Hand-written prost structs for GetGlobalState (proto 1002).
// Field tags match official Futu OpenD proto definition:
// https://github.com/FutunnOpen/py-futu-api/blob/master/futu/common/pb/GetGlobalState.proto

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
    pub market_sh: i32,
    #[prost(int32, required, tag = "4")]
    pub market_sz: i32,
    #[prost(int32, required, tag = "5")]
    pub market_hk_future: i32,
    #[prost(bool, required, tag = "6")]
    pub qot_logined: bool,
    #[prost(bool, required, tag = "7")]
    pub trd_logined: bool,
    #[prost(int32, required, tag = "8")]
    pub server_ver: i32,
    #[prost(int32, required, tag = "9")]
    pub server_build_no: i32,
    #[prost(int64, required, tag = "10")]
    pub time: i64,
    #[prost(double, optional, tag = "11")]
    pub local_time: ::core::option::Option<f64>,
    // tag 12: programStatus (Common.ProgramStatus message) — skipped
    // tag 13: qotSvrIpAddr (string) — skipped
    // tag 14: trdSvrIpAddr (string) — skipped
    #[prost(int32, optional, tag = "15")]
    pub market_us_future: ::core::option::Option<i32>,
    // tag 16: connID (uint64) — skipped
    #[prost(int32, optional, tag = "17")]
    pub market_sg_future: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "18")]
    pub market_jp_future: ::core::option::Option<i32>,
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
