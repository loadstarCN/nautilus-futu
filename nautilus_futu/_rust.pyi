"""Type stubs for the Rust extension module ``nautilus_futu._rust``."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

Security = tuple[int, str]

class PyFutuClient:
    """Thread-safe client for a single Futu OpenD TCP connection."""

    def __init__(self) -> None: ...
    # ── connection ──────────────────────────────────────────────────────
    def connect(
        self,
        host: str,
        port: int,
        client_id: str,
        client_ver: int,
        rsa_key_path: str | None = None,
        request_timeout_secs: int = 15,
    ) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def is_encrypted(self) -> bool: ...
    def connection_generation(self) -> int: ...
    def get_global_state(self) -> dict[str, Any]: ...
    # ── push ────────────────────────────────────────────────────────────
    def start_push(self, proto_ids: list[int]) -> int: ...
    def poll_push(self, channel_id: int, timeout_ms: int = 100) -> dict[str, Any] | None: ...
    def poll_push_async(self, channel_id: int) -> Awaitable[dict[str, Any]]: ...
    # ── quotes ──────────────────────────────────────────────────────────
    def subscribe(self, securities: list[Security], sub_types: list[int], is_sub: bool) -> None: ...
    def get_sub_info(self, is_req_all_conn: bool | None = None) -> dict[str, Any]: ...
    def get_static_info(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def get_basic_qot(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def get_security_snapshot(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def get_order_book(self, market: int, code: str, num: int = 10) -> dict[str, Any]: ...
    def get_ticker(self, market: int, code: str, max_ret_num: int = 100) -> list[dict[str, Any]]: ...
    def get_kl(self, market: int, code: str, rehab_type: int, kl_type: int, req_count: int = 100) -> list[dict[str, Any]]: ...
    def get_history_kl(
        self,
        market: int,
        code: str,
        rehab_type: int,
        kl_type: int,
        begin_time: str,
        end_time: str,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_rt(self, market: int, code: str) -> dict[str, Any]: ...
    def get_broker(self, market: int, code: str) -> dict[str, Any]: ...
    def get_rehab(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def get_suspend(self, securities: list[Security], begin_time: str, end_time: str) -> list[dict[str, Any]]: ...
    def get_plate_set(self, market: int, plate_set_type: int) -> list[dict[str, Any]]: ...
    def get_plate_security(
        self, plate_market: int, plate_code: str, sort_field: int | None = None, ascend: bool | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_reference(self, market: int, code: str, reference_type: int) -> list[dict[str, Any]]: ...
    def get_owner_plate(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def get_option_chain(
        self,
        owner_market: int,
        owner_code: str,
        begin_time: str,
        end_time: str,
        option_type: int | None = None,
        condition: int | None = None,
        index_option_type: int | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_option_expiration_date(
        self, owner_market: int, owner_code: str, index_option_type: int | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_warrant(
        self,
        begin: int,
        num: int,
        sort_field: int,
        ascend: bool,
        owner: Security | None = None,
        type_list: list[int] | None = None,
        issuer_list: list[int] | None = None,
    ) -> dict[str, Any]: ...
    def get_capital_flow(self, market: int, code: str, period_type: int | None = None) -> dict[str, Any]: ...
    def get_capital_distribution(self, market: int, code: str) -> dict[str, Any]: ...
    def get_user_security(self, group_name: str) -> list[dict[str, Any]]: ...
    def modify_user_security(self, group_name: str, op: int, securities: list[Security]) -> dict[str, Any]: ...
    def get_code_change(self, securities: list[Security], type_list: list[int] | None = None) -> list[dict[str, Any]]: ...
    def get_ipo_list(self, market: int) -> list[dict[str, Any]]: ...
    def get_future_info(self, securities: list[Security]) -> list[dict[str, Any]]: ...
    def request_trade_date(
        self, market: int, begin_time: str, end_time: str, security: Security | None = None,
    ) -> list[dict[str, Any]]: ...
    def stock_filter(
        self,
        market: int,
        begin: int = 0,
        num: int = 200,
        base_filters: list[tuple[int, float | None, float | None, int | None]] | None = None,
        accumulate_filters: list[tuple[int, int, float | None, float | None, int | None]] | None = None,
        financial_filters: list[tuple[int, int, float | None, float | None, int | None]] | None = None,
    ) -> dict[str, Any]: ...
    # ── trade ───────────────────────────────────────────────────────────
    def get_acc_list(
        self, trd_category: int | None = None, need_general_sec_account: bool | None = None,
    ) -> list[dict[str, Any]]: ...
    def unlock_trade(self, unlock: bool, pwd_md5: str, security_firm: int = 1) -> None: ...
    def sub_acc_push(self, acc_ids: list[int]) -> None: ...
    def place_order(
        self,
        trd_env: int,
        acc_id: int,
        trd_market: int,
        trd_side: int,
        order_type: int,
        code: str,
        qty: float,
        price: float | None = None,
        sec_market: int | None = None,
        remark: str | None = None,
        time_in_force: int | None = None,
        fill_outside_rth: bool | None = None,
        aux_price: float | None = None,
        trail_type: int | None = None,
        trail_value: float | None = None,
        trail_spread: float | None = None,
        adjust_limit: float | None = None,
    ) -> dict[str, Any]: ...
    def modify_order(
        self,
        trd_env: int,
        acc_id: int,
        trd_market: int,
        order_id: int,
        modify_op: int,
        qty: float | None = None,
        price: float | None = None,
        aux_price: float | None = None,
    ) -> None: ...
    def get_order_list(self, trd_env: int, acc_id: int, trd_market: int) -> list[dict[str, Any]]: ...
    def get_order_fill_list(self, trd_env: int, acc_id: int, trd_market: int) -> list[dict[str, Any]]: ...
    def get_position_list(self, trd_env: int, acc_id: int, trd_market: int) -> list[dict[str, Any]]: ...
    def get_funds(self, trd_env: int, acc_id: int, trd_market: int, currency: int | None = None) -> dict[str, Any]: ...
    # History queries: ``begin_time``/``end_time`` are ``YYYY-MM-DD HH:MM:SS``
    # in market local time; a missing bound defaults to a 90-day window.
    def get_history_order_list(
        self,
        trd_env: int,
        acc_id: int,
        trd_market: int,
        filter_status_list: list[int] | None = None,
        begin_time: str | None = None,
        end_time: str | None = None,
        code_list: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_history_order_fill_list(
        self,
        trd_env: int,
        acc_id: int,
        trd_market: int,
        begin_time: str | None = None,
        end_time: str | None = None,
        code_list: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_max_trd_qtys(
        self,
        trd_env: int,
        acc_id: int,
        trd_market: int,
        order_type: int,
        code: str,
        price: float,
        sec_market: int | None = None,
    ) -> dict[str, Any]: ...
    def get_margin_ratio(
        self, trd_env: int, acc_id: int, trd_market: int, securities: list[Security],
    ) -> list[dict[str, Any]]: ...
    def get_order_fee(
        self, trd_env: int, acc_id: int, trd_market: int, order_id_ex_list: list[str],
    ) -> list[dict[str, Any]]: ...
