# Changelog

## 0.5.0 (2026-09-12)

### Fixed (critical)

- **Order pushes never matched local orders.** The execution client looked orders
  up with `Cache.order(venue_order_id=...)`, which does not exist in NautilusTrader,
  so no `OrderAccepted`/`OrderFilled`/`OrderCanceled` events were ever generated.
  Orders are now indexed with `Cache.add_venue_order_id` after `place_order` and
  resolved from pushes through the cache or through the Futu `remark` field, which
  now carries the `client_order_id` (also enabling reconciliation by client ID).
- **Routing.** `FutuDataClientConfig`/`FutuExecClientConfig` now default to
  `RoutingConfig(venues={HKEX, NYSE, NASDAQ, SSE, SZSE, SGX})`, so instruments such as
  `00700.HKEX` reach the FUTU clients without extra configuration. The execution
  client registers the FUTU account as the account for every venue
  (`set_specific_venue`) instead of inserting zero-balance alias accounts.
- **Disconnect detection.** The Rust client exposes a live connection flag; `poll_push`
  raises `ConnectionError` (instead of returning `None` forever) when the link dies,
  and push channels survive reconnects. Data and execution clients share one
  reference-counted `FutuConnectionManager`, detect reconnects triggered by the other
  client through a connection *generation* counter and restore their own subscriptions.
- **`cancel_all_orders`** now cancels only the strategy's open orders for the command's
  instrument and side, instead of every order in the account across all markets.
- **Quote ticks** are built from the level-1 of the order book stream (real bid/ask)
  instead of `cur_price + price_spread`, whose float arithmetic could exceed Nautilus'
  precision limit and drop ticks. Prices/quantities use the cached instrument precision.

### Fixed

- K-line pushes: only completed bars are emitted (revisions optional via
  `handle_revised_bars`), with a flush loop for the last bar of a session.
- Modify/cancel now generate `OrderUpdated`, `OrderModifyRejected` and
  `OrderCancelRejected`; a venue `FAILED` on a working order is mapped to canceled.
- Requests time out (`request_timeout`, default 15s) instead of hanging forever; the
  keepalive loop also detects half-open links by watching for OpenD replies.
- Historical bars: pagination via `nextReqKey`, market-local time strings with
  seconds for intraday bars, sensible default lookback, `limit=0` means unbounded.
- Balances are cash based (`cash`/`frozen_cash`, per-currency `cash_info_list`),
  margin accounts publish margin balances, balances refresh after order/fill pushes.
- Exchange timestamps are used for `ts_event`; order book deltas carry `F_SNAPSHOT`/`F_LAST`
  flags, sequence numbers and honour `depth`; L3 subscriptions are rejected.
- CN instruments and balances use `CNH` consistently (Futu's only RMB currency).
- Official `SecurityType` values (`Drvt=8`, `Future=10`) are recognised.
- Execution push channel is registered before `sub_acc_push` so no push is lost.

### Added

- Order types: `STOP_MARKET`, `STOP_LIMIT`, `MARKET_IF_TOUCHED`, `LIMIT_IF_TOUCHED`,
  `TRAILING_STOP_MARKET`, `TRAILING_STOP_LIMIT`; `GTC`/`DAY`; US pre/after-market
  fills (`fill_outside_rth` config or `FUTU_RTH:1` order tag).
- `poll_push_async` (pyo3-async-runtimes) so no worker thread is blocked while waiting
  for pushes; `connection_generation`, `is_encrypted`, `get_kl` on `PyFutuClient`.
- RSA/AES encrypted transport wired end-to-end (`rsa_key_path`).
- OpenD `Notify` (1003) decoding: gateway events, connection status, quota usage.
- Instrument provider: batched `load_ids_async`, `load_all_async` with
  `venues`/`markets`/`plates`/`option_chains` filters, `load_option_chain_async`.
- `hk_tick_size()` helper (HKEX spread table); `_rust.pyi` type stubs; `py.typed`.
- Fake OpenD end-to-end tests (Rust and Python), ruff/mypy configuration, CI lint job,
  `regenerate-protos` cargo feature for `prost-build`.

### Changed

- `parse_futu_trade_tick` returns `None` for zero-volume prints.
- `FutuLiveDataClient`/`FutuLiveExecutionClient` accept a `connection` manager;
  the `connect_lock` argument is kept for backwards compatibility only.
- `get_history_kl` follows pagination automatically; `place_order`/`modify_order`
  gained conditional-order parameters.

## 0.4.2 and earlier

See the git history.
