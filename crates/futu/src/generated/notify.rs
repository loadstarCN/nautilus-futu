// Hand-written to match prost-build output for Notify.proto (proto 1003).
//
// Every field except `ret_type` is declared `optional` on purpose: OpenD has
// added/renumbered fields in this message over the years and a missing
// `required` field would make prost reject the whole push.  Unknown fields are
// skipped by prost, so newer OpenD builds keep decoding.

/// `NotifyType` values carried in `S2c.type`.
pub const NOTIFY_TYPE_NONE: i32 = 0;
pub const NOTIFY_TYPE_GTW_EVENT: i32 = 1;
pub const NOTIFY_TYPE_PROGRAM_STATUS: i32 = 2;
pub const NOTIFY_TYPE_CONN_STATUS: i32 = 3;
pub const NOTIFY_TYPE_QOT_RIGHT: i32 = 4;
pub const NOTIFY_TYPE_API_LEVEL: i32 = 5;
pub const NOTIFY_TYPE_API_QUOTA: i32 = 6;
pub const NOTIFY_TYPE_USED_QUOTA: i32 = 7;

/// 网关事件
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GtwEvent {
    /// GtwEventType，事件类型
    #[prost(int32, optional, tag = "1")]
    pub event_type: ::core::option::Option<i32>,
    /// 事件描述
    #[prost(string, optional, tag = "2")]
    pub desc: ::core::option::Option<::prost::alloc::string::String>,
}
/// 程序状态
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ProgramStatus {
    #[prost(message, optional, tag = "1")]
    pub program_status: ::core::option::Option<super::common::ProgramStatus>,
}
/// 连接状态
#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct ConnectStatus {
    /// 行情是否已登录
    #[prost(bool, optional, tag = "1")]
    pub qot_logined: ::core::option::Option<bool>,
    /// 交易是否已登录
    #[prost(bool, optional, tag = "2")]
    pub trd_logined: ::core::option::Option<bool>,
}
/// 行情权限
#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct QotRight {
    #[prost(int32, optional, tag = "4")]
    pub hk_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub us_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub cn_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "7")]
    pub hk_option_qot_right: ::core::option::Option<i32>,
    #[prost(bool, optional, tag = "8")]
    pub has_us_option_qot_right: ::core::option::Option<bool>,
    #[prost(int32, optional, tag = "9")]
    pub hk_future_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "10")]
    pub us_future_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "11")]
    pub sg_future_qot_right: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "12")]
    pub jp_future_qot_right: ::core::option::Option<i32>,
}
/// API 等级
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ApiLevel {
    #[prost(string, optional, tag = "1")]
    pub api_level: ::core::option::Option<::prost::alloc::string::String>,
}
/// API 额度
#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct ApiQuota {
    /// 订阅额度
    #[prost(int32, optional, tag = "1")]
    pub sub_quota: ::core::option::Option<i32>,
    /// 历史K线额度
    #[prost(int32, optional, tag = "2")]
    pub history_kl_quota: ::core::option::Option<i32>,
}
/// 已用额度
#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct UsedQuota {
    #[prost(int32, optional, tag = "1")]
    pub used_sub_quota: ::core::option::Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub used_kline_quota: ::core::option::Option<i32>,
}
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    /// 通知类型，参见 NotifyType
    #[prost(int32, required, tag = "1")]
    pub r#type: i32,
    #[prost(message, optional, tag = "2")]
    pub event: ::core::option::Option<GtwEvent>,
    #[prost(message, optional, tag = "3")]
    pub program_status: ::core::option::Option<ProgramStatus>,
    #[prost(message, optional, tag = "4")]
    pub connect_status: ::core::option::Option<ConnectStatus>,
    #[prost(message, optional, tag = "5")]
    pub qot_right: ::core::option::Option<QotRight>,
    #[prost(message, optional, tag = "6")]
    pub api_level: ::core::option::Option<ApiLevel>,
    #[prost(message, optional, tag = "7")]
    pub api_quota: ::core::option::Option<ApiQuota>,
    #[prost(message, optional, tag = "8")]
    pub used_quota: ::core::option::Option<UsedQuota>,
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
