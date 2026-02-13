//! Subscribe to trading push notifications.

use prost::Message;
use crate::client::FutuClient;
use super::TradeError;

const PROTO_TRD_SUB_ACC_PUSH: u32 = 2008;

/// Subscribe to trading account push notifications for the given account IDs.
pub async fn sub_acc_push(
    client: &FutuClient,
    acc_ids: Vec<u64>,
) -> Result<(), TradeError> {
    let c2s = crate::generated::trd_sub_acc_push::C2s {
        acc_id_list: acc_ids,
    };
    let request = crate::generated::trd_sub_acc_push::Request { c2s };
    let body = request.encode_to_vec();

    let resp = client.request(PROTO_TRD_SUB_ACC_PUSH, &body).await
        .map_err(TradeError::Connection)?;

    let response = crate::generated::trd_sub_acc_push::Response::decode(resp.body.as_slice())
        .map_err(|e| TradeError::Decode(e.to_string()))?;

    if response.ret_type != 0 {
        return Err(TradeError::Server {
            ret_type: response.ret_type,
            msg: response.ret_msg.unwrap_or_default(),
        });
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constant() {
        assert_eq!(PROTO_TRD_SUB_ACC_PUSH, 2008);
    }

    #[test]
    fn test_sub_acc_push_request_encode_decode() {
        let c2s = crate::generated::trd_sub_acc_push::C2s {
            acc_id_list: vec![12345, 67890],
        };
        let request = crate::generated::trd_sub_acc_push::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::trd_sub_acc_push::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.acc_id_list, vec![12345, 67890]);
    }

    #[test]
    fn test_sub_acc_push_response_decode() {
        let response = crate::generated::trd_sub_acc_push::Response {
            ret_type: 0,
            ret_msg: None,
            err_code: None,
            s2c: Some(crate::generated::trd_sub_acc_push::S2c {}),
        };
        let encoded = response.encode_to_vec();
        let decoded = crate::generated::trd_sub_acc_push::Response::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.ret_type, 0);
        assert!(decoded.s2c.is_some());
    }
}
