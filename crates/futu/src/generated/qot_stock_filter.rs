// Hand-written prost structs for Qot_StockFilter (proto_id 3215).
// Tags match official Futu proto: Qot_StockFilter.proto

/// Base attribute filter condition.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BaseFilter {
    /// StockField, attribute field
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    /// Lower bound (closed interval), -inf if omitted
    #[prost(double, optional, tag = "2")]
    pub filter_min: ::core::option::Option<f64>,
    /// Upper bound (closed interval), +inf if omitted
    #[prost(double, optional, tag = "3")]
    pub filter_max: ::core::option::Option<f64>,
    /// True = ignore this filter (useful for sort-only)
    #[prost(bool, optional, tag = "4")]
    pub is_no_filter: ::core::option::Option<bool>,
    /// SortDir, 0=no sort, 1=ascending, 2=descending
    #[prost(int32, optional, tag = "5")]
    pub sort_dir: ::core::option::Option<i32>,
}

/// Accumulate attribute filter condition.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AccumulateFilter {
    /// AccumulateField, attribute field
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    #[prost(double, optional, tag = "2")]
    pub filter_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "3")]
    pub filter_max: ::core::option::Option<f64>,
    #[prost(bool, optional, tag = "4")]
    pub is_no_filter: ::core::option::Option<bool>,
    #[prost(int32, optional, tag = "5")]
    pub sort_dir: ::core::option::Option<i32>,
    /// Number of days for accumulation
    #[prost(int32, required, tag = "6")]
    pub days: i32,
}

/// Financial attribute filter condition.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FinancialFilter {
    /// FinancialField, attribute field
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    #[prost(double, optional, tag = "2")]
    pub filter_min: ::core::option::Option<f64>,
    #[prost(double, optional, tag = "3")]
    pub filter_max: ::core::option::Option<f64>,
    #[prost(bool, optional, tag = "4")]
    pub is_no_filter: ::core::option::Option<bool>,
    #[prost(int32, optional, tag = "5")]
    pub sort_dir: ::core::option::Option<i32>,
    /// FinancialQuarter
    #[prost(int32, required, tag = "6")]
    pub quarter: i32,
}

/// Base data item in response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BaseData {
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    #[prost(double, required, tag = "2")]
    pub value: f64,
}

/// Accumulate data item in response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AccumulateData {
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    #[prost(double, required, tag = "2")]
    pub value: f64,
    #[prost(int32, required, tag = "3")]
    pub days: i32,
}

/// Financial data item in response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FinancialData {
    #[prost(int32, required, tag = "1")]
    pub field_name: i32,
    #[prost(double, required, tag = "2")]
    pub value: f64,
    #[prost(int32, required, tag = "3")]
    pub quarter: i32,
}

/// Single stock result in response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StockData {
    #[prost(message, required, tag = "1")]
    pub security: super::qot_common::Security,
    #[prost(string, required, tag = "2")]
    pub name: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "3")]
    pub base_data_list: ::prost::alloc::vec::Vec<BaseData>,
    #[prost(message, repeated, tag = "4")]
    pub accumulate_data_list: ::prost::alloc::vec::Vec<AccumulateData>,
    #[prost(message, repeated, tag = "5")]
    pub financial_data_list: ::prost::alloc::vec::Vec<FinancialData>,
}

/// C2S request.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    /// Data starting offset (0-based)
    #[prost(int32, required, tag = "1")]
    pub begin: i32,
    /// Number of results to return (max 200)
    #[prost(int32, required, tag = "2")]
    pub num: i32,
    /// QotMarket
    #[prost(int32, required, tag = "3")]
    pub market: i32,
    /// Optional plate security for filtering within a plate
    #[prost(message, optional, tag = "4")]
    pub plate: ::core::option::Option<super::qot_common::Security>,
    #[prost(message, repeated, tag = "5")]
    pub base_filter_list: ::prost::alloc::vec::Vec<BaseFilter>,
    #[prost(message, repeated, tag = "6")]
    pub accumulate_filter_list: ::prost::alloc::vec::Vec<AccumulateFilter>,
    #[prost(message, repeated, tag = "7")]
    pub financial_filter_list: ::prost::alloc::vec::Vec<FinancialFilter>,
}

/// S2C response.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    /// True if this is the last page
    #[prost(bool, required, tag = "1")]
    pub last_page: bool,
    /// Total number of matching records
    #[prost(int32, required, tag = "2")]
    pub all_count: i32,
    #[prost(message, repeated, tag = "3")]
    pub data_list: ::prost::alloc::vec::Vec<StockData>,
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
