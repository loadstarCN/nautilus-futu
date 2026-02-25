use std::sync::Arc;
use std::time::Duration;
use prost::Message;
use tokio::sync::oneshot;
use tokio::time;

use crate::client::connection::{FutuConnection, ConnectionError};

/// ProtoID for KeepAlive
const PROTO_ID_KEEP_ALIVE: u32 = 1004;

/// Start the keepalive heartbeat loop.
/// Returns a JoinHandle that can be used to cancel the loop.
///
/// When keepalive fails `MAX_FAILURES` consecutive times, a signal is sent
/// via `failure_tx` so the recv loop can detect the dead connection.
pub fn start_keepalive(
    conn: Arc<FutuConnection>,
    interval_secs: i32,
    failure_tx: oneshot::Sender<()>,
) -> tokio::task::JoinHandle<()> {
    let interval = Duration::from_secs(interval_secs.max(1) as u64);

    tokio::spawn(async move {
        let mut ticker = time::interval(interval);
        ticker.tick().await; // Skip the first immediate tick
        let mut consecutive_failures: u32 = 0;
        const MAX_FAILURES: u32 = 3;

        loop {
            ticker.tick().await;
            if let Err(e) = send_keepalive(&conn).await {
                consecutive_failures += 1;
                if consecutive_failures >= MAX_FAILURES {
                    tracing::error!("KeepAlive failed {} consecutive times, stopping: {}", MAX_FAILURES, e);
                    let _ = failure_tx.send(());
                    break;
                }
                tracing::warn!("KeepAlive failed (attempt {}/{}): {}", consecutive_failures, MAX_FAILURES, e);
            } else {
                consecutive_failures = 0;
            }
        }
    })
}

async fn send_keepalive(conn: &FutuConnection) -> Result<(), ConnectionError> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;

    let c2s = crate::generated::keep_alive::C2s { time: now };
    let request = crate::generated::keep_alive::Request { c2s };

    let body = request.encode_to_vec();
    conn.send(PROTO_ID_KEEP_ALIVE, &body).await?;
    tracing::debug!("KeepAlive sent, time={}", now);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;

    #[test]
    fn test_proto_id_constant() {
        assert_eq!(PROTO_ID_KEEP_ALIVE, 1004);
    }

    #[test]
    fn test_keepalive_request_encode_decode() {
        let c2s = crate::generated::keep_alive::C2s { time: 1718400000 };
        let request = crate::generated::keep_alive::Request { c2s };
        let encoded = request.encode_to_vec();
        let decoded = crate::generated::keep_alive::Request::decode(encoded.as_slice()).unwrap();
        assert_eq!(decoded.c2s.time, 1718400000);
    }

    #[test]
    fn test_interval_minimum_clamp() {
        // Test the clamping logic used in start_keepalive
        fn clamp_interval(secs: i32) -> Duration {
            Duration::from_secs(secs.max(1) as u64)
        }

        assert_eq!(clamp_interval(0), Duration::from_secs(1));
        assert_eq!(clamp_interval(-5), Duration::from_secs(1));
        assert_eq!(clamp_interval(10), Duration::from_secs(10));
    }
}
