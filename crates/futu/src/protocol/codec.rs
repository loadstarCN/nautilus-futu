use bytes::BytesMut;
use tokio_util::codec::{Decoder, Encoder};

use super::header::{HeaderError, PacketHeader, HEADER_SIZE};

/// A framed message consisting of header + body.
#[derive(Debug, Clone)]
pub struct FutuMessage {
    pub proto_id: u32,
    pub serial_no: u32,
    pub body: Vec<u8>,
}

/// Maximum allowed body size (100 MB) to prevent OOM from malicious/corrupted data.
const MAX_BODY_SIZE: u32 = 100_000_000;

/// Tokio codec for the Futu OpenD binary protocol.
pub struct FutuCodec;

impl Decoder for FutuCodec {
    type Item = FutuMessage;
    type Error = CodecError;

    fn decode(&mut self, src: &mut BytesMut) -> Result<Option<Self::Item>, Self::Error> {
        // Need at least header size
        if src.len() < HEADER_SIZE {
            return Ok(None);
        }

        // Peek at the header to get body length without consuming
        let body_len = {
            let mut peek = src.clone();
            match PacketHeader::decode(&mut peek) {
                Ok(header) => {
                    if header.body_len > MAX_BODY_SIZE {
                        return Err(CodecError::BodyTooLarge(header.body_len));
                    }
                    header.body_len as usize
                }
                Err(HeaderError::InsufficientData) => return Ok(None),
                Err(e) => return Err(CodecError::Header(e)),
            }
        };

        // Check if we have the full packet
        let total_len = HEADER_SIZE + body_len;
        if src.len() < total_len {
            // Reserve space for the rest of the packet
            src.reserve(total_len - src.len());
            return Ok(None);
        }

        // Now consume the header
        let header = PacketHeader::decode(src).map_err(CodecError::Header)?;

        // Extract body
        let body = src.split_to(body_len).to_vec();

        // Verify body SHA1 checksum
        if !header.verify_body(&body) {
            return Err(CodecError::ChecksumMismatch {
                proto_id: header.proto_id,
                serial_no: header.serial_no,
            });
        }

        Ok(Some(FutuMessage {
            proto_id: header.proto_id,
            serial_no: header.serial_no,
            body,
        }))
    }
}

impl Encoder<FutuMessage> for FutuCodec {
    type Error = CodecError;

    fn encode(&mut self, item: FutuMessage, dst: &mut BytesMut) -> Result<(), Self::Error> {
        let header = PacketHeader::new(item.proto_id, item.serial_no, &item.body);
        dst.reserve(HEADER_SIZE + item.body.len());
        header.encode(dst);
        dst.extend_from_slice(&item.body);
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum CodecError {
    #[error("header error: {0}")]
    Header(#[from] HeaderError),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("body too large: {0} bytes (max {MAX_BODY_SIZE})")]
    BodyTooLarge(u32),
    #[error("SHA1 checksum mismatch for proto_id={proto_id}, serial_no={serial_no}")]
    ChecksumMismatch { proto_id: u32, serial_no: u32 },
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio_util::codec::{Decoder, Encoder};

    #[test]
    fn test_codec_roundtrip() {
        let mut codec = FutuCodec;
        let msg = FutuMessage {
            proto_id: 1001,
            serial_no: 42,
            body: b"test body data".to_vec(),
        };

        let mut buf = BytesMut::new();
        codec.encode(msg.clone(), &mut buf).unwrap();

        let decoded = codec.decode(&mut buf).unwrap().unwrap();
        assert_eq!(decoded.proto_id, 1001);
        assert_eq!(decoded.serial_no, 42);
        assert_eq!(decoded.body, b"test body data");
    }

    #[test]
    fn test_codec_partial_header() {
        let mut codec = FutuCodec;
        let mut buf = BytesMut::from(&b"FT"[..]);
        assert!(codec.decode(&mut buf).unwrap().is_none());
    }

    #[test]
    fn test_codec_partial_body() {
        let mut codec = FutuCodec;
        let msg = FutuMessage {
            proto_id: 1001,
            serial_no: 1,
            body: b"hello".to_vec(),
        };

        let mut full_buf = BytesMut::new();
        codec.encode(msg, &mut full_buf).unwrap();

        // Only provide part of the packet
        let partial = full_buf.split_to(HEADER_SIZE + 2);
        let mut buf = BytesMut::from(&partial[..]);
        assert!(codec.decode(&mut buf).unwrap().is_none());
    }

    #[test]
    fn test_codec_multiple_messages() {
        let mut codec = FutuCodec;
        let msg1 = FutuMessage {
            proto_id: 1001,
            serial_no: 1,
            body: b"first".to_vec(),
        };
        let msg2 = FutuMessage {
            proto_id: 3001,
            serial_no: 2,
            body: b"second".to_vec(),
        };

        let mut buf = BytesMut::new();
        codec.encode(msg1, &mut buf).unwrap();
        codec.encode(msg2, &mut buf).unwrap();

        let d1 = codec.decode(&mut buf).unwrap().unwrap();
        assert_eq!(d1.proto_id, 1001);
        assert_eq!(d1.serial_no, 1);
        assert_eq!(d1.body, b"first");

        let d2 = codec.decode(&mut buf).unwrap().unwrap();
        assert_eq!(d2.proto_id, 3001);
        assert_eq!(d2.serial_no, 2);
        assert_eq!(d2.body, b"second");
    }

    #[test]
    fn test_codec_empty_body() {
        let mut codec = FutuCodec;
        let msg = FutuMessage {
            proto_id: 1004,
            serial_no: 10,
            body: vec![],
        };
        let mut buf = BytesMut::new();
        codec.encode(msg, &mut buf).unwrap();

        let decoded = codec.decode(&mut buf).unwrap().unwrap();
        assert_eq!(decoded.proto_id, 1004);
        assert_eq!(decoded.serial_no, 10);
        assert!(decoded.body.is_empty());
    }

    #[test]
    fn test_codec_large_body() {
        let mut codec = FutuCodec;
        let body: Vec<u8> = (0..10240).map(|i| (i % 256) as u8).collect();
        let msg = FutuMessage {
            proto_id: 3103,
            serial_no: 99,
            body: body.clone(),
        };
        let mut buf = BytesMut::new();
        codec.encode(msg, &mut buf).unwrap();

        let decoded = codec.decode(&mut buf).unwrap().unwrap();
        assert_eq!(decoded.proto_id, 3103);
        assert_eq!(decoded.serial_no, 99);
        assert_eq!(decoded.body, body);
    }

    #[test]
    fn test_codec_checksum_mismatch() {
        let mut codec = FutuCodec;
        // Build a valid packet then tamper with the body
        let msg = FutuMessage {
            proto_id: 1001,
            serial_no: 42,
            body: b"original".to_vec(),
        };
        let mut buf = BytesMut::new();
        codec.encode(msg, &mut buf).unwrap();

        // Tamper with the body bytes (after the 44-byte header)
        buf[HEADER_SIZE] ^= 0xFF;

        let result = codec.decode(&mut buf);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, CodecError::ChecksumMismatch { proto_id: 1001, serial_no: 42 }));
    }

    #[test]
    fn test_codec_body_too_large() {
        let mut codec = FutuCodec;
        // Craft a header with body_len exceeding MAX_BODY_SIZE
        let fake_body = b"x";
        let mut header = PacketHeader::new(1001, 1, fake_body);
        header.body_len = MAX_BODY_SIZE + 1;

        let mut buf = BytesMut::new();
        header.encode(&mut buf);
        buf.extend_from_slice(fake_body);

        let result = codec.decode(&mut buf);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, CodecError::BodyTooLarge(_)));
    }
}
