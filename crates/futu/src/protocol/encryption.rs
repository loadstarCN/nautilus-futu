use aes::cipher::{generic_array::GenericArray, BlockDecrypt, BlockEncrypt, KeyInit};
use aes::Aes128;
use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::pkcs8::DecodePrivateKey;
use rsa::traits::PublicKeyParts;
use rsa::{Pkcs1v15Encrypt, RsaPrivateKey, RsaPublicKey};

/// AES-128-ECB encryption (used after InitConnect key exchange).
/// Futu uses standard AES-ECB with PKCS7 padding.
pub struct AesEcbCipher {
    cipher: Aes128,
}

impl AesEcbCipher {
    /// Create from 16-byte key returned by InitConnect.
    pub fn new(key: &[u8; 16]) -> Self {
        let cipher = Aes128::new(GenericArray::from_slice(key));
        Self { cipher }
    }

    /// Encrypt data with PKCS7 padding.
    pub fn encrypt(&self, data: &[u8]) -> Vec<u8> {
        let block_size = 16;
        let padding_len = block_size - (data.len() % block_size);
        let padded_len = data.len() + padding_len;
        let mut padded = Vec::with_capacity(padded_len);
        padded.extend_from_slice(data);
        padded.resize(padded_len, padding_len as u8);

        let mut result = padded;
        for chunk in result.chunks_exact_mut(block_size) {
            let block = GenericArray::from_mut_slice(chunk);
            self.cipher.encrypt_block(block);
        }
        result
    }

    /// Decrypt data and remove PKCS7 padding.
    pub fn decrypt(&self, data: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        if data.is_empty() || !data.len().is_multiple_of(16) {
            return Err(EncryptionError::InvalidCiphertext);
        }

        let mut result = data.to_vec();
        for chunk in result.chunks_exact_mut(16) {
            let block = GenericArray::from_mut_slice(chunk);
            self.cipher.decrypt_block(block);
        }

        // Remove PKCS7 padding
        let padding_len = *result.last().ok_or(EncryptionError::InvalidPadding)? as usize;
        if padding_len == 0 || padding_len > 16 {
            return Err(EncryptionError::InvalidPadding);
        }
        if result.len() < padding_len {
            return Err(EncryptionError::InvalidPadding);
        }
        let data_len = result.len() - padding_len;
        // Verify padding bytes
        for &b in &result[data_len..] {
            if b as usize != padding_len {
                return Err(EncryptionError::InvalidPadding);
            }
        }
        result.truncate(data_len);
        Ok(result)
    }
}

/// RSA PKCS#1 v1.5 cipher used for the `InitConnect` handshake when OpenD is
/// configured with an RSA private key.
///
/// The client and OpenD share the *same* private key.  The request body is
/// encrypted with the public half in chunks of `key_size - 11` bytes, and the
/// response body is decrypted with the private half in chunks of `key_size`
/// bytes.  This mirrors the reference `futu-api` implementation.
pub struct RsaCipher {
    private: RsaPrivateKey,
    public: RsaPublicKey,
    key_size: usize,
}

impl RsaCipher {
    /// Load a PEM-encoded private key (PKCS#1 "RSA PRIVATE KEY" or PKCS#8 "PRIVATE KEY").
    pub fn from_pem(pem: &str) -> Result<Self, EncryptionError> {
        let private = RsaPrivateKey::from_pkcs1_pem(pem)
            .or_else(|_| RsaPrivateKey::from_pkcs8_pem(pem))
            .map_err(|e| EncryptionError::Rsa(format!("invalid RSA private key: {e}")))?;
        let public = RsaPublicKey::from(&private);
        let key_size = private.size();
        Ok(Self { private, public, key_size })
    }

    /// Load a PEM-encoded private key from a file path.
    pub fn from_pem_file(path: &std::path::Path) -> Result<Self, EncryptionError> {
        let pem = std::fs::read_to_string(path)
            .map_err(|e| EncryptionError::Rsa(format!("cannot read {}: {e}", path.display())))?;
        Self::from_pem(&pem)
    }

    /// RSA key size in bytes (e.g. 128 for a 1024-bit key).
    pub fn key_size(&self) -> usize {
        self.key_size
    }

    /// Encrypt with the public key, chunked so any body length is supported.
    pub fn encrypt(&self, data: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        let chunk_size = self.key_size.saturating_sub(11).max(1);
        let mut rng = rand::thread_rng();
        let mut out = Vec::with_capacity(data.len().div_ceil(chunk_size) * self.key_size);
        for chunk in data.chunks(chunk_size) {
            let enc = self
                .public
                .encrypt(&mut rng, Pkcs1v15Encrypt, chunk)
                .map_err(|e| EncryptionError::Rsa(e.to_string()))?;
            out.extend_from_slice(&enc);
        }
        Ok(out)
    }

    /// Decrypt with the private key, chunked by key size.
    pub fn decrypt(&self, data: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        if data.is_empty() || !data.len().is_multiple_of(self.key_size) {
            return Err(EncryptionError::InvalidCiphertext);
        }
        let mut out = Vec::with_capacity(data.len());
        for chunk in data.chunks(self.key_size) {
            let dec = self
                .private
                .decrypt(Pkcs1v15Encrypt, chunk)
                .map_err(|e| EncryptionError::Rsa(e.to_string()))?;
            out.extend_from_slice(&dec);
        }
        Ok(out)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum EncryptionError {
    #[error("invalid ciphertext length")]
    InvalidCiphertext,
    #[error("invalid PKCS7 padding")]
    InvalidPadding,
    #[error("RSA error: {0}")]
    Rsa(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_aes_ecb_roundtrip() {
        let key = [0x01u8; 16];
        let cipher = AesEcbCipher::new(&key);

        let plaintext = b"Hello, Futu OpenD!";
        let encrypted = cipher.encrypt(plaintext);
        let decrypted = cipher.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_aes_ecb_block_aligned() {
        let key = [0x42u8; 16];
        let cipher = AesEcbCipher::new(&key);

        // Exactly 16 bytes - should get full block of padding
        let plaintext = b"0123456789abcdef";
        let encrypted = cipher.encrypt(plaintext);
        assert_eq!(encrypted.len(), 32); // 16 data + 16 padding
        let decrypted = cipher.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_aes_ecb_invalid_ciphertext() {
        let key = [0x01u8; 16];
        let cipher = AesEcbCipher::new(&key);
        assert!(cipher.decrypt(&[0u8; 15]).is_err());
        assert!(cipher.decrypt(&[]).is_err());
    }

    #[test]
    fn test_aes_ecb_single_byte() {
        let key = [0xAAu8; 16];
        let cipher = AesEcbCipher::new(&key);
        let plaintext = &[0x42u8];
        let encrypted = cipher.encrypt(plaintext);
        assert_eq!(encrypted.len(), 16); // 1 byte + 15 padding = 16
        let decrypted = cipher.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_aes_ecb_large_data() {
        let key = [0xBBu8; 16];
        let cipher = AesEcbCipher::new(&key);
        let plaintext: Vec<u8> = (0..1000).map(|i| (i % 256) as u8).collect();
        let encrypted = cipher.encrypt(&plaintext);
        // 1000 bytes + 8 padding = 1008 (multiple of 16)
        assert_eq!(encrypted.len(), 1008);
        let decrypted = cipher.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_aes_ecb_deterministic() {
        let key = [0xCCu8; 16];
        let cipher = AesEcbCipher::new(&key);
        let plaintext = b"deterministic test";
        let enc1 = cipher.encrypt(plaintext);
        let enc2 = cipher.encrypt(plaintext);
        assert_eq!(enc1, enc2);
    }

    #[test]
    fn test_aes_ecb_different_keys() {
        let cipher1 = AesEcbCipher::new(&[0x11u8; 16]);
        let cipher2 = AesEcbCipher::new(&[0x22u8; 16]);
        let plaintext = b"same plaintext";
        let enc1 = cipher1.encrypt(plaintext);
        let enc2 = cipher2.encrypt(plaintext);
        assert_ne!(enc1, enc2);
    }

    #[test]
    fn test_aes_ecb_corrupted_padding() {
        let key = [0xDDu8; 16];
        let cipher = AesEcbCipher::new(&key);
        // Construct a 16-byte block that, when decrypted, will have invalid padding.
        // Encrypt known data, then corrupt the last byte of the ciphertext
        // to produce garbage after decryption.
        let mut ciphertext = cipher.encrypt(b"test");
        // Flip a bit in the last block to corrupt padding after decryption
        let last = ciphertext.len() - 1;
        ciphertext[last] ^= 0xFF;
        assert!(matches!(
            cipher.decrypt(&ciphertext),
            Err(EncryptionError::InvalidPadding)
        ));
    }

    fn test_rsa_cipher() -> RsaCipher {
        // Generating a key is slow in debug builds, so use a small 1024-bit key
        // and share it across assertions.
        let mut rng = rand::thread_rng();
        let private = RsaPrivateKey::new(&mut rng, 1024).expect("keygen");
        let public = RsaPublicKey::from(&private);
        RsaCipher { key_size: private.size(), private, public }
    }

    #[test]
    fn test_rsa_roundtrip_multi_chunk() {
        let cipher = test_rsa_cipher();
        assert_eq!(cipher.key_size(), 128);
        // 300 bytes -> 3 chunks of 117
        let plaintext: Vec<u8> = (0..300).map(|i| (i % 251) as u8).collect();
        let encrypted = cipher.encrypt(&plaintext).unwrap();
        assert_eq!(encrypted.len(), 3 * 128);
        let decrypted = cipher.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_rsa_invalid_ciphertext_length() {
        let cipher = test_rsa_cipher();
        assert!(matches!(
            cipher.decrypt(&[0u8; 100]),
            Err(EncryptionError::InvalidCiphertext)
        ));
        assert!(cipher.decrypt(&[]).is_err());
    }

    #[test]
    fn test_rsa_pem_roundtrip() {
        use rsa::pkcs1::EncodeRsaPrivateKey;
        let mut rng = rand::thread_rng();
        let private = RsaPrivateKey::new(&mut rng, 1024).expect("keygen");
        let pem = private.to_pkcs1_pem(rsa::pkcs1::LineEnding::LF).unwrap();
        let cipher = RsaCipher::from_pem(&pem).unwrap();
        let enc = cipher.encrypt(b"handshake").unwrap();
        assert_eq!(cipher.decrypt(&enc).unwrap(), b"handshake");
        assert!(RsaCipher::from_pem("not a pem").is_err());
    }
}
