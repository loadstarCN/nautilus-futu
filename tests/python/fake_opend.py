"""A minimal in-process fake Futu OpenD for end-to-end tests.

Speaks the real framing protocol (44-byte ``FT`` header + SHA1 body checksum)
and hand-encodes the handful of protobuf messages needed to exercise the Rust
client: ``InitConnect`` (1001), ``KeepAlive`` (1004), ``Qot_Sub`` (3001) and
``Qot_UpdateBasicQot`` (3005) pushes.  Runs an asyncio server on a background
thread so synchronous ``PyFutuClient`` calls can be driven from the test.
"""

from __future__ import annotations

import asyncio
import hashlib
import struct
import threading
import time
from collections.abc import Callable

HEADER_FMT = "<2sIBBII20s8s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
assert HEADER_SIZE == 44


# ---------------------------------------------------------------------------
# Tiny protobuf encoder
# ---------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def f_varint(tag: int, value: int) -> bytes:
    return _varint((tag << 3) | 0) + _varint(int(value))


def f_bytes(tag: int, value: bytes) -> bytes:
    return _varint((tag << 3) | 2) + _varint(len(value)) + value


def f_str(tag: int, value: str) -> bytes:
    return f_bytes(tag, value.encode("utf-8"))


def f_double(tag: int, value: float) -> bytes:
    return _varint((tag << 3) | 1) + struct.pack("<d", float(value))


# ---------------------------------------------------------------------------
# Message bodies
# ---------------------------------------------------------------------------


def init_connect_response(conn_id: int = 7, user_id: int = 42, keepalive: int = 1) -> bytes:
    s2c = (
        f_varint(1, 900)  # serverVer
        + f_varint(2, user_id)  # loginUserID
        + f_varint(3, conn_id)  # connID
        + f_str(4, "")  # connAESKey
        + f_varint(5, keepalive)  # keepAliveInterval
    )
    return f_varint(1, 0) + f_bytes(4, s2c)


def keepalive_response() -> bytes:
    return f_varint(1, 0) + f_bytes(4, f_varint(1, int(time.time())))


def ok_empty_response() -> bytes:
    return f_varint(1, 0) + f_bytes(4, b"")


def error_response(msg: str = "rejected") -> bytes:
    return f_varint(1, -1) + f_str(2, msg)


def basic_qot_push(code: str = "00700", cur_price: float = 345.0, market: int = 1) -> bytes:
    security = f_varint(1, market) + f_str(2, code)
    qot = (
        f_bytes(1, security)
        + f_varint(2, 0)  # isSuspended
        + f_str(3, "2004-06-16")  # listTime
        + f_double(4, 0.2)  # priceSpread
        + f_str(5, "2024-01-01 10:00:00")  # updateTime
        + f_double(6, cur_price + 5)  # high
        + f_double(7, cur_price - 5)  # open
        + f_double(8, cur_price - 10)  # low
        + f_double(9, cur_price)  # cur
        + f_double(10, cur_price - 3)  # lastClose
        + f_varint(11, 1000)  # volume
        + f_double(12, 1.0)  # turnover
        + f_double(13, 0.5)  # turnoverRate
        + f_double(14, 1.0)  # amplitude
        + f_double(18, 1704067200.0)  # updateTimestamp
    )
    return f_varint(1, 0) + f_bytes(4, f_bytes(1, qot))


def frame(proto_id: int, serial_no: int, body: bytes) -> bytes:
    header = struct.pack(
        HEADER_FMT, b"FT", proto_id, 0, 0, serial_no, len(body), hashlib.sha1(body).digest(), b"\0" * 8,
    )
    return header + body


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class FakeOpenD:
    """Background-thread fake OpenD.

    Parameters
    ----------
    ignore_protos : set[int]
        Requests with these proto ids get no reply (to test timeouts).
    """

    def __init__(self, ignore_protos: set[int] | None = None) -> None:
        self.ignore_protos = set(ignore_protos or ())
        self.port = 0
        self.received: list[tuple[int, int]] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._ready = threading.Event()
        self._server: asyncio.AbstractServer | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._stop_event: asyncio.Event | None = None
        self.handlers: dict[int, Callable[[bytes], bytes]] = {
            1001: lambda body: init_connect_response(),
            1004: lambda body: keepalive_response(),
            3001: lambda body: ok_empty_response(),
        }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> FakeOpenD:
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("fake OpenD did not start")
        return self

    def stop(self) -> None:
        if self._loop.is_running() and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(5)
        if not self._loop.is_closed():
            self._loop.close()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        self._stop_event = asyncio.Event()
        self._server = await asyncio.start_server(self._on_client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()
        await self._stop_event.wait()
        await self._close_writers()
        self._server.close()
        await self._server.wait_closed()

    async def _close_writers(self) -> None:
        for w in list(self._writers):
            try:
                w.close()
            except Exception:
                pass
        self._writers.clear()

    # -- protocol ---------------------------------------------------------

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        try:
            while True:
                head = await reader.readexactly(HEADER_SIZE)
                magic, proto_id, _fmt, _ver, serial_no, body_len, _sha, _res = struct.unpack(HEADER_FMT, head)
                assert magic == b"FT"
                body = await reader.readexactly(body_len) if body_len else b""
                self.received.append((proto_id, serial_no))
                if proto_id in self.ignore_protos:
                    continue
                handler = self.handlers.get(proto_id)
                reply = handler(body) if handler else ok_empty_response()
                writer.write(frame(proto_id, serial_no, reply))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if writer in self._writers:
                self._writers.remove(writer)
            try:
                writer.close()
            except Exception:
                pass

    # -- test controls ----------------------------------------------------

    def push(self, proto_id: int, body: bytes) -> None:
        """Send an unsolicited push frame to every connected client."""

        async def _push() -> None:
            for w in list(self._writers):
                w.write(frame(proto_id, 0, body))
                await w.drain()

        asyncio.run_coroutine_threadsafe(_push(), self._loop).result(5)

    def drop_connections(self) -> None:
        """Close every client socket (simulates an OpenD crash/restart)."""
        asyncio.run_coroutine_threadsafe(self._close_writers(), self._loop).result(5)

    @property
    def connection_count(self) -> int:
        return len(self._writers)
