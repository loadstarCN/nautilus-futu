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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = FutuConfig::default();
        assert_eq!(config.host, "127.0.0.1");
        assert_eq!(config.port, 11111);
        assert_eq!(config.client_id, "nautilus_futu");
        assert_eq!(config.client_ver, 100);
        assert!(config.rsa_key_path.is_none());
        assert!(!config.enable_encryption);
        assert!(config.reconnect);
        assert_eq!(config.reconnect_interval_secs, 5);
    }

    #[test]
    fn test_custom_config() {
        let config = FutuConfig {
            host: "192.168.1.100".to_string(),
            port: 22222,
            client_id: "my_client".to_string(),
            client_ver: 200,
            rsa_key_path: Some(PathBuf::from("/tmp/rsa.key")),
            enable_encryption: true,
            reconnect: false,
            reconnect_interval_secs: 10,
        };
        assert_eq!(config.host, "192.168.1.100");
        assert_eq!(config.port, 22222);
        assert_eq!(config.client_id, "my_client");
        assert_eq!(config.client_ver, 200);
        assert_eq!(config.rsa_key_path.unwrap(), PathBuf::from("/tmp/rsa.key"));
        assert!(config.enable_encryption);
        assert!(!config.reconnect);
        assert_eq!(config.reconnect_interval_secs, 10);
    }

    #[test]
    fn test_clone() {
        let config = FutuConfig {
            host: "10.0.0.1".to_string(),
            port: 33333,
            ..FutuConfig::default()
        };
        let cloned = config.clone();
        assert_eq!(cloned.host, config.host);
        assert_eq!(cloned.port, config.port);
        assert_eq!(cloned.client_id, config.client_id);
        assert_eq!(cloned.enable_encryption, config.enable_encryption);
    }
}
