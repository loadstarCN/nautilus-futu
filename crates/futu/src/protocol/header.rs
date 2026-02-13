use bytes::{Buf, BufMut, BytesMut};
use sha1::{Digest, Sha1};

pub const HEADER_SIZE: usize = 44;
pub const HEADER_MAGIC: &[u8; 2] = b"FT";

#[derive(Debug, Clone)]
pub struct PacketHeader {
    pub proto_id: u32,
    pub proto_fmt_type: u8,
    pub proto_ver: u8,
    pub serial_no: u32,
    pub body_len: u32,
    pub body_sha1: [u8; 20],
}

impl PacketHeader {
    pub fn new(proto_id: u32, serial_no: u32, body: &[u8]) -> Self {
        let mut hasher = Sha1::new();
        hasher.update(body);
        let sha1_result = hasher.finalize();
        let mut body_sha1 = [0u8; 20];
        body_sha1.copy_from_slice(&sha1_result);

        Self {
            proto_id,
            proto_fmt_type: 0, // Protobuf
            proto_ver: 0,
            serial_no,
            body_len: body.len() as u32,
            body_sha1,
        }
    }

    pub fn encode(&self, buf: &mut BytesMut) {
        buf.put_slice(HEADER_MAGIC);
        buf.put_u32_le(self.proto_id);
        buf.put_u8(self.proto_fmt_type);
        buf.put_u8(self.proto_ver);
        buf.put_u32_le(self.serial_no);
        buf.put_u32_le(self.body_len);
        buf.put_slice(&self.body_sha1);
        buf.put_bytes(0, 8); // reserved
    }

    pub fn decode(buf: &mut BytesMut) -> Result<Self, HeaderError> {
        if buf.len() < HEADER_SIZE {
            return Err(HeaderError::InsufficientData);
        }

        let magic = &buf[0..2];
        if magic != HEADER_MAGIC {
            return Err(HeaderError::InvalidMagic);
        }

        let proto_id = u32::from_le_bytes([buf[2], buf[3], buf[4], buf[5]]);
        let proto_fmt_type = buf[6];
        let proto_ver = buf[7];
        let serial_no = u32::from_le_bytes([buf[8], buf[9], buf[10], buf[11]]);
        let body_len = u32::from_le_bytes([buf[12], buf[13], buf[14], buf[15]]);
        let mut body_sha1 = [0u8; 20];
        body_sha1.copy_from_slice(&buf[16..36]);
        // Skip reserved bytes 36..44

        buf.advance(HEADER_SIZE);

        Ok(Self {
            proto_id,
            proto_fmt_type,
            proto_ver,
            serial_no,
            body_len,
            body_sha1,
        })
    }

    pub fn verify_body(&self, body: &[u8]) -> bool {
        let mut hasher = Sha1::new();
        hasher.update(body);
        let sha1_result = hasher.finalize();
        sha1_result.as_slice() == self.body_sha1
    }
}

#[derive(Debug, thiserror::Error)]
pub enum HeaderError {
    #[error("insufficient data for header")]
    InsufficientData,
    #[error("invalid magic bytes")]
    InvalidMagic,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_header_roundtrip() {
        let body = b"hello world";
        let header = PacketHeader::new(1001, 1, body);

        let mut buf = BytesMut::new();
        header.encode(&mut buf);
        assert_eq!(buf.len(), HEADER_SIZE);

        let decoded = PacketHeader::decode(&mut buf).unwrap();
        assert_eq!(decoded.proto_id, 1001);
        assert_eq!(decoded.serial_no, 1);
        assert_eq!(decoded.body_len, body.len() as u32);
        assert!(decoded.verify_body(body));
    }

    #[test]
    fn test_header_magic() {
        let mut buf = BytesMut::from(&b"XX"[..]);
        buf.extend_from_slice(&[0u8; 42]);
        assert!(matches!(
            PacketHeader::decode(&mut buf),
            Err(HeaderError::InvalidMagic)
        ));
    }

    #[test]
    fn test_header_insufficient_data() {
        let mut buf = BytesMut::from(&b"FT"[..]);
        assert!(matches!(
            PacketHeader::decode(&mut buf),
            Err(HeaderError::InsufficientData)
        ));
    }

    #[test]
    fn test_header_zero_length_body() {
        let body: &[u8] = b"";
        let header = PacketHeader::new(3001, 5, body);
        assert_eq!(header.body_len, 0);

        let mut buf = BytesMut::new();
        header.encode(&mut buf);
        let decoded = PacketHeader::decode(&mut buf).unwrap();
        assert_eq!(decoded.body_len, 0);
        assert!(decoded.verify_body(body));
    }

    #[test]
    fn test_header_sha1_verification_fail() {
        let body = b"original data";
        let header = PacketHeader::new(1001, 1, body);
        // Verify with different body should fail
        assert!(!header.verify_body(b"tampered data"));
    }

    #[test]
    fn test_header_various_proto_ids() {
        for proto_id in [1001u32, 3001, 3103, u32::MAX] {
            let header = PacketHeader::new(proto_id, 1, b"test");
            let mut buf = BytesMut::new();
            header.encode(&mut buf);
            let decoded = PacketHeader::decode(&mut buf).unwrap();
            assert_eq!(decoded.proto_id, proto_id);
        }
    }
}
