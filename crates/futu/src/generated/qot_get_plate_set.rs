// Hand-written prost structs for Qot_GetPlateSet (proto_id 3204).
// Tags match official Futu proto: Qot_GetPlateSet.proto

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct C2s {
    #[prost(int32, required, tag = "1")]
    pub market: i32,
    #[prost(int32, required, tag = "2")]
    pub plate_set_type: i32,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct S2c {
    #[prost(message, repeated, tag = "1")]
    pub plate_info_list: ::prost::alloc::vec::Vec<super::qot_common::PlateInfo>,
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
