"""Shared OpenD connection management.

A data client and an execution client pointed at the same OpenD share one
``PyFutuClient`` (one TCP connection).  ``FutuConnectionManager`` serialises
connect/disconnect across the two consumers, reference-counts them so the
first ``release()`` does not tear the link down under the other, and exposes
the connection *generation* so each consumer can notice a reconnect that the
other one triggered and restore its own subscriptions.
"""

from __future__ import annotations

import asyncio
from typing import Any


class FutuConnectionManager:
    """Reference-counted owner of a shared ``PyFutuClient``.

    Parameters
    ----------
    client : Any
        The Rust ``PyFutuClient`` instance.
    host, port, client_id, client_ver
        OpenD connection parameters.
    rsa_key_path : str | None
        Optional RSA private key for the encrypted transport.
    request_timeout : float
        Per-request response deadline in seconds.
    """

    def __init__(
        self,
        client: Any,
        host: str,
        port: int,
        client_id: str = "nautilus_futu",
        client_ver: int = 100,
        rsa_key_path: str | None = None,
        request_timeout: float = 15.0,
    ) -> None:
        self.client = client
        self.host = host
        self.port = port
        self.client_id = client_id
        self.client_ver = client_ver
        self.rsa_key_path = rsa_key_path
        self.request_timeout = request_timeout
        self._lock = asyncio.Lock()
        self._refcount = 0

    @property
    def refcount(self) -> int:
        return self._refcount

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self.client.is_connected())
        except Exception:
            return False

    @property
    def generation(self) -> int:
        """Number of successful connects so far (changes on every reconnect)."""
        try:
            return int(self.client.connection_generation())
        except Exception:
            return 0

    def _connect_blocking(self) -> None:
        kwargs: dict[str, Any] = {}
        # Older/mocked clients may not accept the optional keyword arguments.
        if self.rsa_key_path is not None:
            kwargs["rsa_key_path"] = self.rsa_key_path
        if self.request_timeout is not None:
            kwargs["request_timeout_secs"] = max(1, int(round(self.request_timeout)))
        try:
            self.client.connect(self.host, self.port, self.client_id, self.client_ver, **kwargs)
        except TypeError:
            self.client.connect(self.host, self.port, self.client_id, self.client_ver)

    async def ensure_connected(self) -> bool:
        """Connect if the link is down.  Returns True when a new connection was made."""
        async with self._lock:
            if self.is_connected:
                return False
            await asyncio.to_thread(self._connect_blocking)
            return True

    async def acquire(self) -> bool:
        """Register a consumer and make sure the link is up.

        The consumer is only counted when the link is up afterwards, so a
        failed connect does not leave a phantom reference behind.
        """
        async with self._lock:
            if self.is_connected:
                self._refcount += 1
                return False
            await asyncio.to_thread(self._connect_blocking)
            self._refcount += 1
            return True

    async def release(self) -> None:
        """Unregister a consumer; disconnect when the last one leaves."""
        async with self._lock:
            self._refcount = max(0, self._refcount - 1)
            if self._refcount == 0:
                try:
                    await asyncio.to_thread(self.client.disconnect)
                except Exception:
                    pass

    async def force_disconnect(self) -> None:
        """Tear the link down regardless of consumers (used before a reconnect)."""
        async with self._lock:
            try:
                await asyncio.to_thread(self.client.disconnect)
            except Exception:
                pass
