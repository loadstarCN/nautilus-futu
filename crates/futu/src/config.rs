use std::path::PathBuf;

/// Configuration for connecting to Futu OpenD gateway.
#[derive(Debug, Clone)]
pub struct FutuConfig {
    /// OpenD gateway host (default: "127.0.0.1")
    pub host: String,
    /// OpenD gateway port (default: 11111)
    pub port: u16,
    /// Client ID for the connection
    pub client_id: String,
    /// Client version string
    pub client_ver: i32,
    /// Path to RSA private key file (optional, for encrypted connections)
    pub rsa_key_path: Option<PathBuf>,
    /// Enable AES encryption (requires RSA keys configured in FutuOpenD)
    pub enable_encryption: bool,
    /// Reconnect on disconnect
    pub reconnect: bool,
    /// Reconnect interval in seconds
    pub reconnect_interval_secs: u64,
}

impl Default for FutuConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 11111,
            client_id: "nautilus_futu".to_string(),
            client_ver: 100,
            rsa_key_path: None,
            enable_encryption: false,
            reconnect: true,
            reconnect_interval_secs: 5,
        }
    }
}
