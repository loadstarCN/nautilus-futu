use std::sync::Arc;
use std::time::Duration;
use prost::Message;
use tokio::time;

use crate::client::connection::{FutuConnection, ConnectionError};

/// ProtoID for KeepAlive
const PROTO_ID_KEEP_ALIVE: u32 = 1004;

/// Start the keepalive heartbeat loop.
/// Returns a JoinHandle that can be used to cancel the loop.
pub fn start_keepalive(
    conn: Arc<FutuConnection>,
    interval_secs: i32,
) -> tokio::task::JoinHandle<()> {
    let interval = Duration::from_secs(interval_secs.max(1) as u64);

    tokio::spawn(async move {
        let mut ticker = time::interval(interval);
        ticker.tick().await; // Skip the first immediate tick

        loop {
            ticker.tick().await;
            if let Err(e) = send_keepalive(&conn).await {
                tracing::error!("KeepAlive failed: {}", e);
                break;
            }
        }
    })
}

async fn send_keepalive(conn: &FutuConnection) -> Result<(), ConnectionError> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;

    let c2s = crate::generated::keep_alive::C2s { time: now };
    let request = crate::generated::keep_alive::Request { c2s };

    let body = request.encode_to_vec();
    conn.send(PROTO_ID_KEEP_ALIVE, &body).await?;
    tracing::debug!("KeepAlive sent, time={}", now);
    Ok(())
}
