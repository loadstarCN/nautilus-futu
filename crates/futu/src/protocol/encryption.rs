use aes::cipher::{generic_array::GenericArray, BlockDecrypt, BlockEncrypt, KeyInit};
use aes::Aes128;

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
        if data.is_empty() || data.len() % 16 != 0 {
            return Err(EncryptionError::InvalidCiphertext);
        }

        let mut result = data.to_vec();
        for chunk in result.chunks_exact_mut(16) {
            let block = GenericArray::from_mut_slice(chunk);
            self.cipher.decrypt_block(block);
        }

        // Remove PKCS7 padding
        let padding_len = *result.last().unwrap() as usize;
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
}
