# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Build Rust + install Python package (development mode)
maturin develop --release

# Run Rust tests only
cargo test -p nautilus-futu

# Run Python tests only
python -X utf8 -m pytest tests/python/ -v

# Run a single Python test
python -X utf8 -m pytest tests/python/test_parsing.py::TestOrderConversion::test_buy_side_conversion -v

# Run a single Rust test
cargo test -p nautilus-futu test_codec_roundtrip

# Windows: use -X utf8 for Chinese character output
python -X utf8 -m pytest tests/python/ -v
```

## Architecture

This is a **Rust (PyO3) + Python hybrid** project that implements a Futu OpenD adapter for NautilusTrader. Built with `maturin`, the Rust code compiles into a Python extension module at `nautilus_futu._rust`.

### Data Flow

```
NautilusTrader ←→ Python adapter layer (nautilus_futu/) ←→ PyO3 ←→ Rust client ←→ TCP/Protobuf ←→ Futu OpenD
```

### Rust Layer (`crates/futu/src/`)

- **`protocol/`** — Binary TCP protocol: 44-byte packet header (`header.rs`), framed codec (`codec.rs`), AES-ECB encryption (`encryption.rs`)
- **`client/`** — Connection management (`connection.rs`), InitConnect handshake (`init.rs`), heartbeat loop (`keepalive.rs`), request/push message dispatcher (`dispatcher.rs`)
- **`quote/`** — Market data: subscription (`subscribe.rs`), snapshots & static info (`snapshot.rs`), K-line history (`history.rs`)
- **`trade/`** — Trading: account & unlock (`account.rs`), place/modify orders (`order.rs`), query orders/positions/funds (`query.rs`)
- **`generated/`** — prost-generated Protobuf types from `crates/futu/proto/*.proto`. Rebuilt by `build.rs`
- **`python/client.rs`** — `PyFutuClient` PyO3 class exposing Rust functions to Python

### Python Layer (`nautilus_futu/`)

- **`data.py`** / **`execution.py`** — NautilusTrader `LiveDataClient` / `LiveExecutionClient` implementations
- **`providers.py`** — `FutuInstrumentProvider` for loading instruments
- **`factories.py`** — Factory classes for NautilusTrader node registration
- **`config.py`** — `FutuDataClientConfig` / `FutuExecClientConfig`
- **`constants.py`** — Venue mappings, market codes, order type enums, SubType/KLType values
- **`common.py`** — Utilities: `instrument_id_to_futu_security()`, `futu_security_to_instrument_id()`, datetime parsing
- **`parsing/`** — Type conversions between Futu and NautilusTrader: `orders.py`, `instruments.py`, `market_data.py`

### Key Patterns

- **PyO3 GIL release**: All blocking Rust calls use `py.allow_threads(|| self.runtime.block_on(...))` to avoid deadlocking Python's GIL
- **TCP connection split**: Uses `tokio::io::split()` + `FramedRead`/`FramedWrite` (NOT `futures::StreamExt::split()` which causes BiLock deadlock)
- **Request dispatching**: Register response dispatcher BEFORE sending request to avoid race condition with the recv loop
- **Protobuf handling**: Rust side uses prost (no Python protobuf dependency), avoiding version conflicts with NautilusTrader

## Futu OpenD Protocol Notes

- **Proto IDs**: InitConnect=1001, KeepAlive=1004, Qot_Sub=3001, Qot_GetBasicQot=3004, Qot_GetKL=3006, Qot_RequestHistoryKL=3103, Qot_GetStaticInfo=3202, TrdGetAccList=2001, TrdPlaceOrder=2202
- **Encryption**: Only active when RSA keys are configured in FutuOpenD. Default `packet_enc_algo=-1` (None). Auto-detect: if response body length is not a multiple of 16, server is not encrypting
- **Packet header**: 44 bytes — magic "FT" (2) + proto_id (4) + fmt (1) + ver (1) + serial_no (4) + body_len (4) + sha1 (20) + reserved (8)
- **Market codes (QotMarket)**: 1=HK, 2=HK_Future, 11=US, 21=CN_SH, 22=CN_SZ, 31=SG
- **TrdSecMarket**: 1=HK, 2=US, 31=CN_SH, 32=CN_SZ, 41=SG (different from QotMarket!)
