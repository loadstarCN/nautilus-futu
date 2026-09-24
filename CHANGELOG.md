# Changelog

## Unreleased

### Fixed

- `PyFutuClient.get_history_order_list` / `get_history_order_fill_list` sent no
  time range, which OpenD requires for history queries.  They now take
  `begin_time`/`end_time` (market local time) and `code_list`.  Missing bounds
  follow the official SDK: the last 90 days, or 90 days from the one bound
  given.  History orders also carry `last_err_msg`.
- `generate_order_status_reports` / `generate_fill_reports` honour the command's
  `instrument_id` (they previously returned every order/fill of the market).
- Fill reports skip fills the venue cancelled (`status == 1`), as the push path
  already did.
- Cancels and modifies no longer fail with "no venue_order_id" when they arrive
  before the order's acceptance push: the venue order id indexed at placement is
  used, and a request that arrives while `place_order` is still in flight is
  applied once the order is placed (several modifies are merged field by field).
  Such orders are accepted when the venue acknowledges the request, so they no
  longer stay stuck in PENDING_UPDATE/PENDING_CANCEL.
- `cancel_all_orders` (and therefore `market_exit`) also cancels in-flight
  SUBMITTED orders, including orders still being placed.
- `OrderAccepted` is emitted once per order even when several pushes arrive
  before the execution engine has applied the first one.
- A `place_order` failure after the request was sent (timeout, lost link) no
  longer reports the order as rejected, since OpenD may have accepted it.  The
  order stays SUBMITTED and the client looks it up in OpenD's order list (by
  `remark`) until its fate is known; an order push or a status report (in-flight
  check, reconciliation) resolves it just as well.  Cancels/modifies made
  meanwhile are applied once, and a modify applied before placement is reported
  when the order is identified.  An order that is never found is rejected; one
  that OpenD works although NautilusTrader already closed it is canceled.
  Requests refused because the link was already down (the Rust client now
  reports "not connected (request not sent)") and OpenD refusals are still
  rejected immediately.
- Fill pushes that arrive before the order they belong to is identified are
  kept and replayed instead of being dropped.
- A refused repeat cancel of an order whose earlier cancel went through (e.g.
  cancel-all plus the OCO manager) no longer produces `OrderCancelRejected`; an
  order accepted only to recover from a refused modify/cancel is reported as
  rejected (not canceled) if the venue later fails it.

### Added

- Reconciliation lookback: when `start` reaches before the current trading day
  (e.g. `reconciliation_lookback_mins`), order and fill reports merge the order /
  fill history with today's lists, so fills made while the node was offline
  reconcile (venue-cancelled fills are skipped).  A single-order status query
  falls back to the history only for cached orders created on an earlier day.
- `subscribe_order_book_depth`: `OrderBookDepth10` snapshots (with per-level
  order counts) from the shared order book stream.
- `subscribe_instrument_status`: OpenD market states (lunch break, closing
  auction, pre/after market, US overnight, futures sessions...) mapped to
  `InstrumentStatus`, polled every `market_status_interval` seconds (default 10)
  while subscribed.  HK futures and index options follow the futures market
  state (instruments missing from the cache are loaded on subscribe).  Options report a daily close as `POST_CLOSE` until they expire,
  because NautilusTrader treats `CLOSE` on an option-chain instrument as expiry.
- `submit_order_list`: independent orders and OCO/OUO groups are placed one by
  one after every leg is validated and marked SUBMITTED (so the strategy's
  `manage_contingent_orders` sees all legs).  When an OCO/OUO leg is rejected or
  canceled before placement, the not yet placed legs linked to it are canceled
  instead of placed; a modify for a queued leg is placed directly; legs the
  engine closed while earlier legs were placed are skipped.  OTO/bracket
  lists are rejected with a hint to use `emulation_trigger` (Futu has no native
  contingent orders).

## 0.5.1 (2026-09-12)

Second review round after 0.5.0.

### Fixed

- Encrypted transport: AES is only enabled when OpenD actually answered the RSA
  handshake; an RSA-configured client talking to a plaintext OpenD now stays in
  plaintext instead of sending AES-encrypted requests it cannot answer.
- Account refresh failures no longer publish a zero balance (which made the risk
  engine deny every order); the last known state is kept. The initial connect
  still registers the account with zeros when the funds query fails.
- `FutuConnectionManager.acquire()` no longer counts a consumer when the connect
  fails, so `release()` tears the link down correctly afterwards.
- Account discovery treats a missing `acc_status` as active instead of skipping
  the account and falling back to the first one.
- Rejection reasons no longer fall back to the `remark` (which holds the client
  order id); the Futu status is reported instead.
- A venue acknowledgement arriving while a modify is pending no longer emits a
  duplicate `OrderUpdated`.
- `fillOutsideRTH` is only sent for US orders.
- `PyFutuClient.connect()` is serialised with a lock (GIL released), so concurrent
  callers can never open two sockets; "not connected" and "disconnected" both
  raise `ConnectionError` from `poll_push` so polling loops reconnect uniformly.

### Added

- Quote-tick fallback: when the order book stream cannot be subscribed (no depth
  quota, e.g. HK BMP accounts) the client subscribes BasicQot and synthesises
  bid/ask from last price and spread, with a warning.
- Gateway notifications (1003) are logged by whichever client opened the
  connection, so an execution-only setup still reports them.

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
