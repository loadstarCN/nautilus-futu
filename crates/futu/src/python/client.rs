#![allow(clippy::useless_conversion)]

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use pyo3::prelude::*;
use pyo3::exceptions::{PyConnectionError, PyRuntimeError};
use parking_lot::Mutex as SyncMutex;
use tokio::runtime::Runtime;
use tokio::sync::{mpsc, Mutex};

use crate::config::FutuConfig;
use crate::client::FutuClient;

type PushMessage = (u32, Vec<u8>);
type PushSender = mpsc::UnboundedSender<PushMessage>;
type PushReceiver = Arc<Mutex<mpsc::UnboundedReceiver<PushMessage>>>;

enum PollOutcome {
    Message(PushMessage),
    Timeout,
    Disconnected,
}

/// One consumer of push messages (a data client or an execution client).
///
/// The channel outlives the TCP connection: on every (re)connect the
/// forwarder tasks are rebuilt from `proto_ids`, so a `channel_id` handed out
/// by `start_push()` stays valid for the life of the `PyFutuClient`.
struct PushChannel {
    tx: PushSender,
    rx: PushReceiver,
    proto_ids: Vec<u32>,
    handles: Vec<tokio::task::JoinHandle<()>>,
}

/// Python-facing Futu client.
///
/// All `#[pymethods]` take `&self` (not `&mut self`) to avoid PyO3's internal
/// RefCell exclusive borrow.  Mutable state is guarded by `SyncMutex` and the
/// lock is never held across `py.allow_threads()` boundaries.
#[pyclass]
pub struct PyFutuClient {
    runtime: Runtime,
    client: SyncMutex<Option<Arc<FutuClient>>>,
    /// Each `start_push()` call creates its own channel so data and
    /// execution clients don't compete for the same receiver.
    push_channels: SyncMutex<Vec<PushChannel>>,
    /// Incremented on every successful `connect()`.  Consumers compare it
    /// against the value they last saw to learn that a reconnect happened
    /// (possibly triggered by another consumer) and re-subscribe.
    generation: AtomicU64,
    /// Serialises `connect()` so two callers can never open two sockets.
    /// Only ever taken with the GIL released.
    connect_lock: SyncMutex<()>,
}

impl PyFutuClient {
    /// Lock `self.client`, clone the `Arc`, and return it.
    /// The `SyncMutex` guard is dropped immediately so it is never held
    /// across `py.allow_threads()` boundaries.
    fn get_client(&self) -> PyResult<Arc<FutuClient>> {
        self.client
            .lock()
            .as_ref()
            .cloned()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))
    }

    /// Like `get_client` but also verifies the recv loop is alive.
    /// Both "never connected / explicitly disconnected" and "link died" map to
    /// `ConnectionError` so a polling loop can treat them alike and reconnect.
    fn get_live_client(&self) -> PyResult<Arc<FutuClient>> {
        let client = self
            .client
            .lock()
            .as_ref()
            .cloned()
            .ok_or_else(|| PyConnectionError::new_err("Not connected to Futu OpenD"))?;
        if !client.is_connected() {
            return Err(PyConnectionError::new_err("Disconnected from Futu OpenD"));
        }
        Ok(client)
    }

    /// (Re)build the forwarder tasks of every registered push channel against
    /// `client`.  Must be called with no `SyncMutex` held by the caller.
    fn wire_push_channels(&self, client: &Arc<FutuClient>) {
        let mut channels = self.push_channels.lock();
        for channel in channels.iter_mut() {
            for handle in channel.handles.drain(..) {
                handle.abort();
            }
            for proto_id in channel.proto_ids.clone() {
                let mut push_rx = self.runtime.block_on(client.subscribe_push(proto_id));
                let tx = channel.tx.clone();
                let handle = self.runtime.spawn(async move {
                    while let Some(msg) = push_rx.recv().await {
                        if tx.send((msg.proto_id, msg.body)).is_err() {
                            break;
                        }
                    }
                });
                channel.handles.push(handle);
            }
        }
    }

    /// Abort every forwarder task but keep the channels (and any queued
    /// messages) so consumers survive a reconnect.
    fn unwire_push_channels(&self) {
        let mut channels = self.push_channels.lock();
        for channel in channels.iter_mut() {
            for handle in channel.handles.drain(..) {
                handle.abort();
            }
        }
    }
}

#[pymethods]
impl PyFutuClient {
    #[new]
    fn new() -> PyResult<Self> {
        let runtime = Runtime::new()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to create runtime: {}", e)))?;
        Ok(Self {
            runtime,
            client: SyncMutex::new(None),
            push_channels: SyncMutex::new(Vec::new()),
            generation: AtomicU64::new(0),
            connect_lock: SyncMutex::new(()),
        })
    }

    /// Connect to Futu OpenD gateway.
    ///
    /// Idempotent: returns immediately when a live connection already exists.
    /// When the previous connection has died, it is replaced and every push
    /// channel created by `start_push()` is re-attached to the new one.
    ///
    /// `rsa_key_path`: PEM private key shared with OpenD to enable the
    /// RSA/AES encrypted transport.  `request_timeout_secs`: per-request
    /// response deadline.
    #[pyo3(signature = (host, port, client_id, client_ver, rsa_key_path=None, request_timeout_secs=15))]
    #[allow(clippy::too_many_arguments)]
    fn connect(
        &self,
        py: Python<'_>,
        host: &str,
        port: u16,
        client_id: &str,
        client_ver: i32,
        rsa_key_path: Option<String>,
        request_timeout_secs: u64,
    ) -> PyResult<()> {
        let config = FutuConfig {
            host: host.to_string(),
            port,
            client_id: client_id.to_string(),
            client_ver,
            rsa_key_path: rsa_key_path.map(std::path::PathBuf::from),
            enable_encryption: false,
            request_timeout_secs,
            ..Default::default()
        };

        // Everything below runs without the GIL: the connect lock serialises
        // concurrent callers (a second caller blocks here, then sees the live
        // connection and returns), and neither the tokio work nor the
        // channel re-wiring touches Python objects.
        py.allow_threads(|| {
            let _serialised = self.connect_lock.lock();

            if let Some(existing) = self.client.lock().as_ref() {
                if existing.is_connected() {
                    return Ok(());
                }
            }

            let mut client = self.runtime.block_on(async {
                FutuClient::connect(config).await
            }).map_err(|e| e.to_string())?;

            self.runtime.block_on(async {
                client.init().await
            }).map_err(|e| e.to_string())?;

            let client = Arc::new(client);
            // Drop the dead client (if any) and install the new one
            *self.client.lock() = Some(Arc::clone(&client));
            self.wire_push_channels(&client);
            self.generation.fetch_add(1, Ordering::SeqCst);
            Ok::<_, String>(())
        }).map_err(|e| PyRuntimeError::new_err(format!("Connection failed: {}", e)))
    }

    /// Disconnect from Futu OpenD.
    ///
    /// Push channels are kept so a later `connect()` re-attaches them.
    fn disconnect(&self, py: Python<'_>) -> PyResult<()> {
        self.unwire_push_channels();

        // Take the Arc out — when the last Arc reference is dropped,
        // FutuClient::drop() aborts keepalive and recv handles.
        let client = self.client.lock().take();
        if let Some(client) = client {
            py.allow_threads(|| {
                self.runtime.block_on(async {
                    client.clear_pending().await;
                });
            });
        }
        tracing::info!("Disconnected from Futu OpenD");
        Ok(())
    }

    /// Number of successful `connect()` calls so far.  Changes whenever the
    /// underlying TCP connection was replaced.
    fn connection_generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }

    /// Check if the client is connected to Futu OpenD *and* the connection is
    /// still alive (recv loop running).
    fn is_connected(&self) -> bool {
        self.client
            .lock()
            .as_ref()
            .map(|c| c.is_connected())
            .unwrap_or(false)
    }

    /// Whether the current connection negotiated AES encryption.
    fn is_encrypted(&self) -> bool {
        self.client
            .lock()
            .as_ref()
            .and_then(|c| c.init_response().map(|r| r.encrypted))
            .unwrap_or(false)
    }

    /// Subscribe to quote data.
    /// securities: list of (market, code) tuples
    /// sub_types: list of SubType integers
    /// is_sub: True to subscribe, False to unsubscribe
    fn subscribe(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
        sub_types: Vec<i32>,
        is_sub: bool,
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::subscribe::subscribe(client, securities, sub_types, is_sub).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Subscribe failed: {}", e)))
    }

    /// Get static info for securities.
    /// securities: list of (market, code) tuples
    /// Returns list of dicts with static info.
    fn get_static_info(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_static_info(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get static info failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.static_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let basic = &info.basic;
                let sec = &basic.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("name", &basic.name)?;
                dict.set_item("lot_size", basic.lot_size)?;
                dict.set_item("sec_type", basic.sec_type)?;
                dict.set_item("list_time", &basic.list_time)?;

                // Extended fields
                if let Some(exch_type) = basic.exch_type {
                    dict.set_item("exch_type", exch_type)?;
                }

                // Option extended data (sec_type=7)
                if let Some(ref opt) = info.option_ex_data {
                    dict.set_item("option_type", opt.r#type)?;
                    dict.set_item("option_owner_market", opt.owner.market)?;
                    dict.set_item("option_owner_code", &opt.owner.code)?;
                    dict.set_item("strike_price", opt.strike_price)?;
                    dict.set_item("strike_time", &opt.strike_time)?;
                    if let Some(ts) = opt.strike_timestamp {
                        dict.set_item("strike_timestamp", ts)?;
                    }
                }

                // Future extended data (sec_type=8)
                if let Some(ref fut) = info.future_ex_data {
                    dict.set_item("last_trade_time", &fut.last_trade_time)?;
                    if let Some(ts) = fut.last_trade_timestamp {
                        dict.set_item("last_trade_timestamp", ts)?;
                    }
                    dict.set_item("is_main_contract", fut.is_main_contract)?;
                }

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get order book for a single security.
    /// Returns a dict with asks and bids lists.
    #[pyo3(signature = (market, code, num=10))]
    fn get_order_book(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        num: i32,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_order_book(client, market, code, num).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get order book failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            let asks = pyo3::types::PyList::empty_bound(py);
            for ob in &s2c.order_book_ask_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("price", ob.price)?;
                d.set_item("volume", ob.volume)?;
                d.set_item("order_count", ob.order_count)?;
                asks.append(d)?;
            }
            dict.set_item("asks", asks)?;

            let bids = pyo3::types::PyList::empty_bound(py);
            for ob in &s2c.order_book_bid_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("price", ob.price)?;
                d.set_item("volume", ob.volume)?;
                d.set_item("order_count", ob.order_count)?;
                bids.append(d)?;
            }
            dict.set_item("bids", bids)?;
        }
        Ok(dict.into_any().unbind())
    }

    /// Get ticker (trade ticks) for a single security.
    /// Returns a list of ticker dicts.
    #[pyo3(signature = (market, code, max_ret_num=100))]
    fn get_ticker(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        max_ret_num: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_ticker(client, market, code, max_ret_num).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get ticker failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for t in &s2c.ticker_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("price", t.price)?;
                dict.set_item("volume", t.volume)?;
                dict.set_item("dir", t.dir)?;
                dict.set_item("sequence", t.sequence)?;
                dict.set_item("turnover", t.turnover)?;
                if let Some(ts) = t.timestamp {
                    dict.set_item("timestamp", ts)?;
                }
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get basic quote data.
    fn get_basic_qot(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_basic_qot(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get basic qot failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for qot in s2c.basic_qot_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let sec = &qot.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("name", &qot.name)?;
                dict.set_item("cur_price", qot.cur_price)?;
                dict.set_item("price_spread", qot.price_spread)?;
                dict.set_item("open_price", qot.open_price)?;
                dict.set_item("high_price", qot.high_price)?;
                dict.set_item("low_price", qot.low_price)?;
                dict.set_item("last_close_price", qot.last_close_price)?;
                dict.set_item("volume", qot.volume)?;
                dict.set_item("turnover", qot.turnover)?;
                dict.set_item("turnover_rate", qot.turnover_rate)?;
                dict.set_item("update_timestamp", qot.update_timestamp)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get historical K-line data (Qot_RequestHistoryKL, proto 3103).
    ///
    /// Follows `next_req_key` pagination automatically until `max_count`
    /// bars are collected (or all bars in the range when `max_count` is None).
    /// Time strings accept "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS".
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (market, code, rehab_type, kl_type, begin_time, end_time, max_count=None))]
    fn get_history_kl(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        rehab_type: i32,
        kl_type: i32,
        begin_time: String,
        end_time: String,
        max_count: Option<i32>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let kl_list = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::history::get_history_kl_all(
                    client, market, code, rehab_type, kl_type,
                    begin_time, end_time, max_count,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get history KL failed: {}", e)))?;

        let mut result = Vec::with_capacity(kl_list.len());
        for kl in kl_list {
            result.push(kline_to_dict(py, &kl)?);
        }
        Ok(result)
    }

    /// Get the most recent K-lines for a *subscribed* security (Qot_GetKL, proto 3006).
    /// Unlike `get_history_kl` this does not consume history quota.
    #[pyo3(signature = (market, code, rehab_type, kl_type, req_count=100))]
    fn get_kl(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        rehab_type: i32,
        kl_type: i32,
        req_count: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::history::get_kl(client, market, code, rehab_type, kl_type, req_count).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get KL failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for kl in &s2c.kl_list {
                result.push(kline_to_dict(py, kl)?);
            }
        }
        Ok(result)
    }

    /// Get account list.
    #[pyo3(signature = (trd_category=None, need_general_sec_account=None))]
    fn get_acc_list(
        &self,
        py: Python<'_>,
        trd_category: Option<i32>,
        need_general_sec_account: Option<bool>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let user_id = client.init_response()
            .map(|r| r.login_user_id)
            .unwrap_or(0);

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::account::get_acc_list(client, user_id, trd_category, need_general_sec_account).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get acc list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for acc in s2c.acc_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("acc_id", acc.acc_id)?;
                dict.set_item("trd_env", acc.trd_env)?;
                dict.set_item("trd_market_auth_list", &acc.trd_market_auth_list)?;
                dict.set_item("acc_type", acc.acc_type)?;
                dict.set_item("card_num", acc.card_num.as_deref())?;
                dict.set_item("security_firm", acc.security_firm)?;
                dict.set_item("sim_acc_type", acc.sim_acc_type)?;
                dict.set_item("uni_card_num", acc.uni_card_num.as_deref())?;
                dict.set_item("acc_status", acc.acc_status)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Unlock trading.
    /// security_firm: 1=FutuSecurities, 2=FutuInc, 3=FutuSG, etc.
    #[pyo3(signature = (unlock, pwd_md5, security_firm=1))]
    fn unlock_trade(
        &self,
        py: Python<'_>,
        unlock: bool,
        pwd_md5: String,
        security_firm: i32,
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::account::unlock_trade(client, unlock, pwd_md5, Some(security_firm)).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Unlock trade failed: {}", e)))
    }

    /// Place an order.
    /// sec_market: 1=HK, 2=US, 31=CN_SH, 32=CN_SZ, etc.
    /// remark: free text (<=64 bytes) echoed back on order pushes/queries;
    ///         the adapter stores the Nautilus client_order_id here.
    /// time_in_force: 0=DAY, 1=GTC.  fill_outside_rth: US pre/after market.
    /// aux_price: trigger price for STOP/STOP_LIMIT/MIT/LIT orders.
    /// trail_type/trail_value/trail_spread: trailing stop parameters.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (trd_env, acc_id, trd_market, trd_side, order_type, code, qty, price=None, sec_market=None,
                        remark=None, time_in_force=None, fill_outside_rth=None, aux_price=None,
                        trail_type=None, trail_value=None, trail_spread=None, adjust_limit=None))]
    fn place_order(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        trd_side: i32,
        order_type: i32,
        code: String,
        qty: f64,
        price: Option<f64>,
        sec_market: Option<i32>,
        remark: Option<String>,
        time_in_force: Option<i32>,
        fill_outside_rth: Option<bool>,
        aux_price: Option<f64>,
        trail_type: Option<i32>,
        trail_value: Option<f64>,
        trail_spread: Option<f64>,
        adjust_limit: Option<f64>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::order::place_order(
                    client, trd_env, acc_id, trd_market,
                    trd_side, order_type, code, qty, price,
                    adjust_limit, sec_market, remark, time_in_force, fill_outside_rth,
                    aux_price, trail_type, trail_value, trail_spread,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Place order failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("order_id", s2c.order_id)?;
            dict.set_item("order_id_ex", s2c.order_id_ex)?;
        }
        Ok(dict.into_any().unbind())
    }

    /// Modify an order.
    #[allow(clippy::too_many_arguments)]
    /// modify_op: 1=Normal (change qty/price), 2=Cancel, 3=Disable, 4=Enable, 5=Delete.
    /// aux_price / trail_*: new trigger / trailing parameters for conditional orders.
    #[pyo3(signature = (trd_env, acc_id, trd_market, order_id, modify_op, qty=None, price=None,
                        aux_price=None, trail_type=None, trail_value=None, trail_spread=None))]
    fn modify_order(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        order_id: u64,
        modify_op: i32,
        qty: Option<f64>,
        price: Option<f64>,
        aux_price: Option<f64>,
        trail_type: Option<i32>,
        trail_value: Option<f64>,
        trail_spread: Option<f64>,
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::order::modify_order(
                    client, trd_env, acc_id, trd_market,
                    order_id, modify_op, qty, price, None,
                    aux_price, trail_type, trail_value, trail_spread,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Modify order failed: {}", e)))?;

        Ok(())
    }

    /// Get order list.
    /// Returns list of dicts with order details.
    fn get_order_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_order_list(client, trd_env, acc_id, trd_market, None).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get order list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for order in s2c.order_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("trd_side", order.trd_side)?;
                dict.set_item("order_type", order.order_type)?;
                dict.set_item("order_status", order.order_status)?;
                dict.set_item("order_id", order.order_id)?;
                dict.set_item("order_id_ex", &order.order_id_ex)?;
                dict.set_item("code", &order.code)?;
                dict.set_item("name", &order.name)?;
                dict.set_item("qty", order.qty)?;
                dict.set_item("price", order.price)?;
                dict.set_item("create_time", &order.create_time)?;
                dict.set_item("update_time", &order.update_time)?;
                dict.set_item("fill_qty", order.fill_qty)?;
                dict.set_item("fill_avg_price", order.fill_avg_price)?;
                dict.set_item("sec_market", order.sec_market)?;
                dict.set_item("create_timestamp", order.create_timestamp)?;
                dict.set_item("update_timestamp", order.update_timestamp)?;
                dict.set_item("time_in_force", order.time_in_force)?;
                dict.set_item("remark", &order.remark)?;
                dict.set_item("last_err_msg", &order.last_err_msg)?;
                dict.set_item("fill_outside_rth", order.fill_outside_rth)?;
                dict.set_item("aux_price", order.aux_price)?;
                dict.set_item("trail_type", order.trail_type)?;
                dict.set_item("trail_value", order.trail_value)?;
                dict.set_item("trail_spread", order.trail_spread)?;
                dict.set_item("currency", order.currency)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get order fill list.
    /// Returns list of dicts with fill details.
    fn get_order_fill_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_order_fill_list(client, trd_env, acc_id, trd_market, None).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get order fill list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for fill in s2c.order_fill_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("trd_side", fill.trd_side)?;
                dict.set_item("fill_id", fill.fill_id)?;
                dict.set_item("fill_id_ex", &fill.fill_id_ex)?;
                dict.set_item("order_id", fill.order_id)?;
                dict.set_item("order_id_ex", fill.order_id_ex.as_deref())?;
                dict.set_item("code", &fill.code)?;
                dict.set_item("name", &fill.name)?;
                dict.set_item("qty", fill.qty)?;
                dict.set_item("price", fill.price)?;
                dict.set_item("create_time", &fill.create_time)?;
                dict.set_item("create_timestamp", fill.create_timestamp)?;
                dict.set_item("update_timestamp", fill.update_timestamp)?;
                dict.set_item("sec_market", fill.sec_market)?;
                dict.set_item("status", fill.status)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get position list.
    /// Returns list of dicts with position details.
    fn get_position_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_position_list(client, trd_env, acc_id, trd_market, None).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get position list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for pos in s2c.position_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("position_id", pos.position_id)?;
                dict.set_item("position_side", pos.position_side)?;
                dict.set_item("code", &pos.code)?;
                dict.set_item("name", &pos.name)?;
                dict.set_item("qty", pos.qty)?;
                dict.set_item("can_sell_qty", pos.can_sell_qty)?;
                dict.set_item("price", pos.price)?;
                dict.set_item("cost_price", pos.cost_price)?;
                dict.set_item("val", pos.val)?;
                dict.set_item("pl_val", pos.pl_val)?;
                dict.set_item("pl_ratio", pos.pl_ratio)?;
                dict.set_item("sec_market", pos.sec_market)?;
                dict.set_item("unrealized_pl", pos.unrealized_pl)?;
                dict.set_item("realized_pl", pos.realized_pl)?;
                dict.set_item("currency", pos.currency)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get account funds.
    /// Returns a dict with fund details.
    #[pyo3(signature = (trd_env, acc_id, trd_market, currency=None))]
    fn get_funds(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        currency: Option<i32>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_funds(client, trd_env, acc_id, trd_market, currency).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get funds failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            if let Some(funds) = s2c.funds {
                dict.set_item("power", funds.power)?;
                dict.set_item("total_assets", funds.total_assets)?;
                dict.set_item("cash", funds.cash)?;
                dict.set_item("market_val", funds.market_val)?;
                dict.set_item("frozen_cash", funds.frozen_cash)?;
                dict.set_item("debt_cash", funds.debt_cash)?;
                dict.set_item("avl_withdrawal_cash", funds.avl_withdrawal_cash)?;
                dict.set_item("currency", funds.currency)?;
                dict.set_item("available_funds", funds.available_funds)?;
                dict.set_item("unrealized_pl", funds.unrealized_pl)?;
                dict.set_item("realized_pl", funds.realized_pl)?;
                dict.set_item("risk_level", funds.risk_level)?;
                dict.set_item("initial_margin", funds.initial_margin)?;
                dict.set_item("maintenance_margin", funds.maintenance_margin)?;
                dict.set_item("max_withdrawal", funds.max_withdrawal)?;
                dict.set_item("net_cash_power", funds.net_cash_power)?;
                dict.set_item("long_mv", funds.long_mv)?;
                dict.set_item("short_mv", funds.short_mv)?;
                dict.set_item("securities_assets", funds.securities_assets)?;

                // Per-currency cash breakdown (unified / futures accounts)
                let cash_list = pyo3::types::PyList::empty_bound(py);
                for ci in &funds.cash_info_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("currency", ci.currency)?;
                    d.set_item("cash", ci.cash)?;
                    d.set_item("available_balance", ci.available_balance)?;
                    d.set_item("net_cash_power", ci.net_cash_power)?;
                    cash_list.append(d)?;
                }
                dict.set_item("cash_info_list", cash_list)?;
            }
        }
        Ok(dict.into_any().unbind())
    }

    /// Get security snapshot.
    /// securities: list of (market, code) tuples
    /// Returns list of dicts with snapshot data.
    fn get_security_snapshot(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_security_snapshot(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get snapshot failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for snapshot in s2c.snapshot_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let basic = &snapshot.basic;
                let sec = &basic.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("type", basic.r#type)?;
                dict.set_item("is_suspend", basic.is_suspend)?;
                dict.set_item("lot_size", basic.lot_size)?;
                dict.set_item("cur_price", basic.cur_price)?;
                dict.set_item("open_price", basic.open_price)?;
                dict.set_item("high_price", basic.high_price)?;
                dict.set_item("low_price", basic.low_price)?;
                dict.set_item("last_close_price", basic.last_close_price)?;
                dict.set_item("volume", basic.volume)?;
                dict.set_item("turnover", basic.turnover)?;
                dict.set_item("update_time", &basic.update_time)?;
                dict.set_item("update_timestamp", basic.update_timestamp)?;
                dict.set_item("ask_price", basic.ask_price)?;
                dict.set_item("bid_price", basic.bid_price)?;
                dict.set_item("ask_vol", basic.ask_vol)?;
                dict.set_item("bid_vol", basic.bid_vol)?;
                dict.set_item("price_spread", basic.price_spread)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Subscribe to trade account push notifications.
    /// acc_ids: list of account IDs to subscribe
    fn sub_acc_push(
        &self,
        py: Python<'_>,
        acc_ids: Vec<u64>,
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::push::sub_acc_push(client, acc_ids).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Sub acc push failed: {}", e)))
    }

    /// Start receiving push notifications for the given proto_ids.
    /// Each call creates a **new** channel and returns its index.
    /// Data and execution clients should each call this once and store
    /// their own `channel_id` for use with `poll_push()`.
    ///
    /// The channel survives reconnects: after `connect()` replaces a dead
    /// connection, pushes for the same proto_ids keep flowing into it.
    fn start_push(
        &self,
        _py: Python<'_>,
        proto_ids: Vec<u32>,
    ) -> PyResult<usize> {
        let (tx, rx) = mpsc::unbounded_channel::<PushMessage>();
        let rx = Arc::new(Mutex::new(rx));

        let channel_id = {
            let mut channels = self.push_channels.lock();
            let id = channels.len();
            channels.push(PushChannel { tx, rx, proto_ids, handles: Vec::new() });
            id
        };

        // Attach immediately when a live connection exists; otherwise the
        // next `connect()` will do it.
        if let Ok(client) = self.get_live_client() {
            self.wire_push_channels(&client);
        }

        Ok(channel_id)
    }

    /// Poll for the next push message on a specific channel.
    /// channel_id: index returned by `start_push()`
    /// timeout_ms: how long to wait for a message (in milliseconds)
    ///
    /// Returns `None` on timeout.  Raises `ConnectionError` when the
    /// connection is down so callers can trigger a reconnect instead of
    /// spinning forever.
    #[pyo3(signature = (channel_id, timeout_ms=100))]
    fn poll_push(
        &self,
        py: Python<'_>,
        channel_id: usize,
        timeout_ms: u64,
    ) -> PyResult<Option<PyObject>> {
        let rx = {
            let channels = self.push_channels.lock();
            match channels.get(channel_id) {
                Some(channel) => Arc::clone(&channel.rx),
                None => return Err(PyRuntimeError::new_err(format!("Unknown push channel_id={}", channel_id))),
            }
        };
        let client = self.get_live_client()?;
        let mut connected = client.connected_watch();

        let timeout = std::time::Duration::from_millis(timeout_ms);

        let result = py.allow_threads(|| {
            self.runtime.block_on(async {
                let mut guard = rx.lock().await;
                // Drain queued messages first even if the link just died so
                // nothing that already arrived is lost.
                if let Ok(msg) = guard.try_recv() {
                    return PollOutcome::Message(msg);
                }
                tokio::select! {
                    res = tokio::time::timeout(timeout, guard.recv()) => match res {
                        Ok(Some(msg)) => PollOutcome::Message(msg),
                        Ok(None) => PollOutcome::Disconnected,
                        Err(_) => PollOutcome::Timeout,
                    },
                    _ = connected.wait_for(|c| !*c) => PollOutcome::Disconnected,
                }
            })
        });

        match result {
            PollOutcome::Message((proto_id, body)) => {
                let data = super::push_decode::decode_push_message(py, proto_id, &body)?;
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("proto_id", proto_id)?;
                dict.set_item("data", data)?;
                Ok(Some(dict.into_any().unbind()))
            }
            PollOutcome::Timeout => Ok(None),
            PollOutcome::Disconnected => Err(PyConnectionError::new_err("Disconnected from Futu OpenD")),
        }
    }

    /// Awaitable variant of `poll_push()` for asyncio callers.
    ///
    /// Resolves with the next push dict, or raises `ConnectionError` when the
    /// connection dies.  No worker thread is blocked while waiting.
    fn poll_push_async<'py>(
        &self,
        py: Python<'py>,
        channel_id: usize,
    ) -> PyResult<Bound<'py, PyAny>> {
        let rx = {
            let channels = self.push_channels.lock();
            match channels.get(channel_id) {
                Some(channel) => Arc::clone(&channel.rx),
                None => return Err(PyRuntimeError::new_err(format!("Unknown push channel_id={}", channel_id))),
            }
        };
        let client = self.get_live_client()?;
        let mut connected = client.connected_watch();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = rx.lock().await;
            let outcome = if let Ok(msg) = guard.try_recv() {
                PollOutcome::Message(msg)
            } else {
                tokio::select! {
                    res = guard.recv() => match res {
                        Some(msg) => PollOutcome::Message(msg),
                        None => PollOutcome::Disconnected,
                    },
                    _ = connected.wait_for(|c| !*c) => PollOutcome::Disconnected,
                }
            };
            drop(guard);
            match outcome {
                PollOutcome::Message((proto_id, body)) => Python::with_gil(|py| {
                    let data = super::push_decode::decode_push_message(py, proto_id, &body)?;
                    let dict = pyo3::types::PyDict::new_bound(py);
                    dict.set_item("proto_id", proto_id)?;
                    dict.set_item("data", data)?;
                    Ok(dict.into_any().unbind())
                }),
                _ => Err(PyConnectionError::new_err("Disconnected from Futu OpenD")),
            }
        })
    }

    /// Filter stocks by conditions (Qot_StockFilter, proto 3215).
    /// base_filters: list of (fieldName, filterMin, filterMax, sortDir)
    /// accumulate_filters: list of (fieldName, days, filterMin, filterMax, sortDir)
    /// financial_filters: list of (fieldName, quarter, filterMin, filterMax, sortDir)
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    #[pyo3(signature = (market, begin=0, num=200, base_filters=None, accumulate_filters=None, financial_filters=None))]
    fn stock_filter(
        &self,
        py: Python<'_>,
        market: i32,
        begin: i32,
        num: i32,
        base_filters: Option<Vec<(i32, Option<f64>, Option<f64>, Option<i32>)>>,
        accumulate_filters: Option<Vec<(i32, i32, Option<f64>, Option<f64>, Option<i32>)>>,
        financial_filters: Option<Vec<(i32, i32, Option<f64>, Option<f64>, Option<i32>)>>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let base = base_filters.unwrap_or_default().into_iter().map(|(field, min, max, sort)| {
            crate::generated::qot_stock_filter::BaseFilter {
                field_name: field,
                filter_min: min,
                filter_max: max,
                is_no_filter: None,
                sort_dir: sort,
            }
        }).collect();

        let accumulate = accumulate_filters.unwrap_or_default().into_iter().map(|(field, days, min, max, sort)| {
            crate::generated::qot_stock_filter::AccumulateFilter {
                field_name: field,
                filter_min: min,
                filter_max: max,
                is_no_filter: None,
                sort_dir: sort,
                days,
            }
        }).collect();

        let financial = financial_filters.unwrap_or_default().into_iter().map(|(field, quarter, min, max, sort)| {
            crate::generated::qot_stock_filter::FinancialFilter {
                field_name: field,
                filter_min: min,
                filter_max: max,
                is_no_filter: None,
                sort_dir: sort,
                quarter,
            }
        }).collect();

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::stock_filter(
                    client, begin, num, market, None, base, accumulate, financial,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Stock filter failed: {}", e)))?;

        let result = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            result.set_item("last_page", s2c.last_page)?;
            result.set_item("all_count", s2c.all_count)?;

            let data_list = pyo3::types::PyList::empty_bound(py);
            for stock in &s2c.data_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", stock.security.market)?;
                dict.set_item("code", &stock.security.code)?;
                dict.set_item("name", &stock.name)?;

                let base_data = pyo3::types::PyList::empty_bound(py);
                for bd in &stock.base_data_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("field", bd.field_name)?;
                    d.set_item("value", bd.value)?;
                    base_data.append(d)?;
                }
                dict.set_item("base_data", base_data)?;

                let acc_data = pyo3::types::PyList::empty_bound(py);
                for ad in &stock.accumulate_data_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("field", ad.field_name)?;
                    d.set_item("value", ad.value)?;
                    d.set_item("days", ad.days)?;
                    acc_data.append(d)?;
                }
                dict.set_item("accumulate_data", acc_data)?;

                let fin_data = pyo3::types::PyList::empty_bound(py);
                for fd in &stock.financial_data_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("field", fd.field_name)?;
                    d.set_item("value", fd.value)?;
                    d.set_item("quarter", fd.quarter)?;
                    fin_data.append(d)?;
                }
                dict.set_item("financial_data", fin_data)?;

                data_list.append(dict)?;
            }
            result.set_item("data", data_list)?;
        }
        Ok(result.into_any().unbind())
    }

    /// Get securities in a plate/sector (Qot_GetPlateSecurity, proto 3205).
    /// Returns a list of static info dicts (same format as get_static_info).
    #[pyo3(signature = (plate_market, plate_code, sort_field=None, ascend=None))]
    fn get_plate_security(
        &self,
        py: Python<'_>,
        plate_market: i32,
        plate_code: String,
        sort_field: Option<i32>,
        ascend: Option<bool>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_plate_security(
                    client, plate_market, plate_code, sort_field, ascend,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get plate security failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.static_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let basic = &info.basic;
                let sec = &basic.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("name", &basic.name)?;
                dict.set_item("lot_size", basic.lot_size)?;
                dict.set_item("sec_type", basic.sec_type)?;
                dict.set_item("list_time", &basic.list_time)?;

                if let Some(exch_type) = basic.exch_type {
                    dict.set_item("exch_type", exch_type)?;
                }

                if let Some(ref opt) = info.option_ex_data {
                    dict.set_item("option_type", opt.r#type)?;
                    dict.set_item("option_owner_market", opt.owner.market)?;
                    dict.set_item("option_owner_code", &opt.owner.code)?;
                    dict.set_item("strike_price", opt.strike_price)?;
                    dict.set_item("strike_time", &opt.strike_time)?;
                    if let Some(ts) = opt.strike_timestamp {
                        dict.set_item("strike_timestamp", ts)?;
                    }
                }

                if let Some(ref fut) = info.future_ex_data {
                    dict.set_item("last_trade_time", &fut.last_trade_time)?;
                    if let Some(ts) = fut.last_trade_timestamp {
                        dict.set_item("last_trade_timestamp", ts)?;
                    }
                    dict.set_item("is_main_contract", fut.is_main_contract)?;
                }

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Trade: get_history_order_list ──────────────────────────────────
    /// Get historical order list.
    /// Returns list of dicts with order details.
    ///
    /// `begin_time`/`end_time` (`YYYY-MM-DD HH:MM:SS`, market local time) are
    /// required by OpenD.  Missing bounds follow the official SDK: neither
    /// given -> the last 90 days (ending one day after now); only `end_time` ->
    /// the 90 days before it; only `begin_time` -> 90 days from it, at most
    /// until one day after now.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (trd_env, acc_id, trd_market, filter_status_list=None, begin_time=None, end_time=None, code_list=None))]
    fn get_history_order_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        filter_status_list: Option<Vec<i32>>,
        begin_time: Option<String>,
        end_time: Option<String>,
        code_list: Option<Vec<String>>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;
        let filter = crate::trade::query::history_filter_conditions(
            begin_time, end_time, code_list.unwrap_or_default(), crate::trade::query::unix_now_secs(),
        );

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_history_order_list(
                    client, trd_env, acc_id, trd_market, Some(filter),
                    filter_status_list.unwrap_or_default(),
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get history order list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for order in s2c.order_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("trd_side", order.trd_side)?;
                dict.set_item("order_type", order.order_type)?;
                dict.set_item("order_status", order.order_status)?;
                dict.set_item("order_id", order.order_id)?;
                dict.set_item("order_id_ex", &order.order_id_ex)?;
                dict.set_item("code", &order.code)?;
                dict.set_item("name", &order.name)?;
                dict.set_item("qty", order.qty)?;
                dict.set_item("price", order.price)?;
                dict.set_item("create_time", &order.create_time)?;
                dict.set_item("update_time", &order.update_time)?;
                dict.set_item("fill_qty", order.fill_qty)?;
                dict.set_item("fill_avg_price", order.fill_avg_price)?;
                dict.set_item("sec_market", order.sec_market)?;
                dict.set_item("create_timestamp", order.create_timestamp)?;
                dict.set_item("update_timestamp", order.update_timestamp)?;
                dict.set_item("time_in_force", order.time_in_force)?;
                dict.set_item("remark", &order.remark)?;
                dict.set_item("last_err_msg", &order.last_err_msg)?;
                dict.set_item("fill_outside_rth", order.fill_outside_rth)?;
                dict.set_item("aux_price", order.aux_price)?;
                dict.set_item("trail_type", order.trail_type)?;
                dict.set_item("trail_value", order.trail_value)?;
                dict.set_item("trail_spread", order.trail_spread)?;
                dict.set_item("currency", order.currency)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Trade: get_history_order_fill_list ───────────────────────────────
    /// Get historical order fill list.
    /// Returns list of dicts with fill details.
    ///
    /// Time bounds and defaults as for `get_history_order_list`.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (trd_env, acc_id, trd_market, begin_time=None, end_time=None, code_list=None))]
    fn get_history_order_fill_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        begin_time: Option<String>,
        end_time: Option<String>,
        code_list: Option<Vec<String>>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;
        let filter = crate::trade::query::history_filter_conditions(
            begin_time, end_time, code_list.unwrap_or_default(), crate::trade::query::unix_now_secs(),
        );

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_history_order_fill_list(
                    client, trd_env, acc_id, trd_market, Some(filter),
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get history order fill list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for fill in s2c.order_fill_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("trd_side", fill.trd_side)?;
                dict.set_item("fill_id", fill.fill_id)?;
                dict.set_item("fill_id_ex", &fill.fill_id_ex)?;
                dict.set_item("order_id", fill.order_id)?;
                dict.set_item("order_id_ex", fill.order_id_ex.as_deref())?;
                dict.set_item("code", &fill.code)?;
                dict.set_item("name", &fill.name)?;
                dict.set_item("qty", fill.qty)?;
                dict.set_item("price", fill.price)?;
                dict.set_item("create_time", &fill.create_time)?;
                dict.set_item("create_timestamp", fill.create_timestamp)?;
                dict.set_item("update_timestamp", fill.update_timestamp)?;
                dict.set_item("sec_market", fill.sec_market)?;
                dict.set_item("status", fill.status)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Trade: get_max_trd_qtys ─────────────────────────────────────────
    /// Get maximum tradeable quantities.
    /// Returns a dict with max qty fields.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (trd_env, acc_id, trd_market, order_type, code, price, sec_market=None))]
    fn get_max_trd_qtys(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        order_type: i32,
        code: String,
        price: f64,
        sec_market: Option<i32>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_max_trd_qtys(
                    client, trd_env, acc_id, trd_market,
                    order_type, code, price, sec_market,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get max trd qtys failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            if let Some(qtys) = s2c.max_trd_qtys {
                dict.set_item("max_cash_buy", qtys.max_cash_buy)?;
                dict.set_item("max_cash_and_margin_buy", qtys.max_cash_and_margin_buy)?;
                dict.set_item("max_position_sell", qtys.max_position_sell)?;
                dict.set_item("max_sell_short", qtys.max_sell_short)?;
                dict.set_item("max_buy_back", qtys.max_buy_back)?;
                dict.set_item("long_required_im", qtys.long_required_im)?;
                dict.set_item("short_required_im", qtys.short_required_im)?;
            }
        }
        Ok(dict.into_any().unbind())
    }

    // ── Trade: get_margin_ratio ─────────────────────────────────────────
    /// Get margin ratio for securities.
    /// Returns list of dicts with margin ratio info.
    fn get_margin_ratio(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_margin_ratio(
                    client, trd_env, acc_id, trd_market, securities,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get margin ratio failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.margin_ratio_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", info.security.market)?;
                dict.set_item("code", &info.security.code)?;
                dict.set_item("is_long_permit", info.is_long_permit)?;
                dict.set_item("is_short_permit", info.is_short_permit)?;
                dict.set_item("short_pool_remain", info.short_pool_remain)?;
                dict.set_item("short_fee_rate", info.short_fee_rate)?;
                dict.set_item("im_long_ratio", info.im_long_ratio)?;
                dict.set_item("im_short_ratio", info.im_short_ratio)?;
                dict.set_item("mm_long_ratio", info.mm_long_ratio)?;
                dict.set_item("mm_short_ratio", info.mm_short_ratio)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Trade: get_order_fee ────────────────────────────────────────────
    /// Get order fee details.
    /// Returns list of dicts with fee info.
    fn get_order_fee(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        order_id_ex_list: Vec<String>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_order_fee(
                    client, trd_env, acc_id, trd_market, order_id_ex_list,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get order fee failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for fee in s2c.order_fee_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("order_id_ex", &fee.order_id_ex)?;
                dict.set_item("fee_amount", fee.fee_amount)?;

                let fee_list = pyo3::types::PyList::empty_bound(py);
                for item in &fee.fee_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("title", item.title.as_deref())?;
                    d.set_item("value", item.value)?;
                    fee_list.append(d)?;
                }
                dict.set_item("fee_list", fee_list)?;

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_sub_info ─────────────────────────────────────────────
    /// Get subscription info.
    /// Returns a dict with quota and subscription details.
    #[pyo3(signature = (is_req_all_conn=None))]
    fn get_sub_info(
        &self,
        py: Python<'_>,
        is_req_all_conn: Option<bool>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_sub_info(client, is_req_all_conn).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get sub info failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("total_used_quota", s2c.total_used_quota)?;
            dict.set_item("remain_quota", s2c.remain_quota)?;

            let conn_list = pyo3::types::PyList::empty_bound(py);
            for conn in &s2c.conn_sub_info_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("used_quota", conn.used_quota)?;
                d.set_item("is_own_conn_data", conn.is_own_conn_data)?;

                let sub_list = pyo3::types::PyList::empty_bound(py);
                for sub in &conn.sub_info_list {
                    let sd = pyo3::types::PyDict::new_bound(py);
                    sd.set_item("sub_type", sub.sub_type)?;
                    let sec_list = pyo3::types::PyList::empty_bound(py);
                    for sec in &sub.security_list {
                        let sec_d = pyo3::types::PyDict::new_bound(py);
                        sec_d.set_item("market", sec.market)?;
                        sec_d.set_item("code", &sec.code)?;
                        sec_list.append(sec_d)?;
                    }
                    sd.set_item("security_list", sec_list)?;
                    sub_list.append(sd)?;
                }
                d.set_item("sub_info_list", sub_list)?;
                conn_list.append(d)?;
            }
            dict.set_item("conn_sub_info_list", conn_list)?;
        }
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_rt ───────────────────────────────────────────────────
    /// Get real-time (time-sharing) data for a single security.
    /// Returns a dict with security info and rt_list.
    fn get_rt(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_rt(client, market, code).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get RT failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("market", s2c.security.market)?;
            dict.set_item("code", &s2c.security.code)?;
            dict.set_item("name", s2c.name.as_deref())?;

            let rt_list = pyo3::types::PyList::empty_bound(py);
            for rt in &s2c.rt_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("time", &rt.time)?;
                d.set_item("minute", rt.minute)?;
                d.set_item("is_blank", rt.is_blank)?;
                d.set_item("price", rt.price)?;
                d.set_item("last_close_price", rt.last_close_price)?;
                d.set_item("avg_price", rt.avg_price)?;
                d.set_item("volume", rt.volume)?;
                d.set_item("turnover", rt.turnover)?;
                d.set_item("timestamp", rt.timestamp)?;
                rt_list.append(d)?;
            }
            dict.set_item("rt_list", rt_list)?;
        }
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_broker ───────────────────────────────────────────────
    /// Get broker queue for a single security.
    /// Returns a dict with broker_ask_list and broker_bid_list.
    fn get_broker(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_broker(client, market, code).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get broker failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            let ask_list = pyo3::types::PyList::empty_bound(py);
            for b in &s2c.broker_ask_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("id", b.id)?;
                d.set_item("name", &b.name)?;
                d.set_item("pos", b.pos)?;
                ask_list.append(d)?;
            }
            dict.set_item("broker_ask_list", ask_list)?;

            let bid_list = pyo3::types::PyList::empty_bound(py);
            for b in &s2c.broker_bid_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("id", b.id)?;
                d.set_item("name", &b.name)?;
                d.set_item("pos", b.pos)?;
                bid_list.append(d)?;
            }
            dict.set_item("broker_bid_list", bid_list)?;
        }
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_rehab ────────────────────────────────────────────────
    /// Get rehabilitation (adjustment) data for securities.
    /// Returns list of dicts with security and rehab_list.
    fn get_rehab(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_rehab(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get rehab failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for sec_rehab in s2c.security_rehab_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", sec_rehab.security.market)?;
                dict.set_item("code", &sec_rehab.security.code)?;

                let rehab_list = pyo3::types::PyList::empty_bound(py);
                for r in &sec_rehab.rehab_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("time", &r.time)?;
                    d.set_item("company_act_flag", r.company_act_flag)?;
                    d.set_item("fwd_factor_a", r.fwd_factor_a)?;
                    d.set_item("fwd_factor_b", r.fwd_factor_b)?;
                    d.set_item("bwd_factor_a", r.bwd_factor_a)?;
                    d.set_item("bwd_factor_b", r.bwd_factor_b)?;
                    d.set_item("split_base", r.split_base)?;
                    d.set_item("split_ert", r.split_ert)?;
                    d.set_item("join_base", r.join_base)?;
                    d.set_item("join_ert", r.join_ert)?;
                    rehab_list.append(d)?;
                }
                dict.set_item("rehab_list", rehab_list)?;

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_suspend ──────────────────────────────────────────────
    /// Get suspension info for securities.
    /// Returns list of dicts with security and suspend_list.
    fn get_suspend(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
        begin_time: String,
        end_time: String,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_suspend(client, securities, begin_time, end_time).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get suspend failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for sec_suspend in s2c.security_suspend_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", sec_suspend.security.market)?;
                dict.set_item("code", &sec_suspend.security.code)?;

                let suspend_list = pyo3::types::PyList::empty_bound(py);
                for s in &sec_suspend.suspend_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("time", &s.time)?;
                    d.set_item("timestamp", s.timestamp)?;
                    suspend_list.append(d)?;
                }
                dict.set_item("suspend_list", suspend_list)?;

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_plate_set ────────────────────────────────────────────
    /// Get plate set (sector list) for a market.
    /// Returns list of dicts with plate info.
    fn get_plate_set(
        &self,
        py: Python<'_>,
        market: i32,
        plate_set_type: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_plate_set(client, market, plate_set_type).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get plate set failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for plate in s2c.plate_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("plate_market", plate.plate.market)?;
                dict.set_item("plate_code", &plate.plate.code)?;
                dict.set_item("name", &plate.name)?;
                dict.set_item("plate_type", plate.plate_type)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_reference ────────────────────────────────────────────
    /// Get reference data (related securities) for a single security.
    /// Returns list of static info dicts.
    fn get_reference(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        reference_type: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_reference(client, market, code, reference_type).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get reference failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.static_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let basic = &info.basic;
                let sec = &basic.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("name", &basic.name)?;
                dict.set_item("lot_size", basic.lot_size)?;
                dict.set_item("sec_type", basic.sec_type)?;
                dict.set_item("list_time", &basic.list_time)?;
                if let Some(exch_type) = basic.exch_type {
                    dict.set_item("exch_type", exch_type)?;
                }
                if let Some(ref opt) = info.option_ex_data {
                    dict.set_item("option_type", opt.r#type)?;
                    dict.set_item("option_owner_market", opt.owner.market)?;
                    dict.set_item("option_owner_code", &opt.owner.code)?;
                    dict.set_item("strike_price", opt.strike_price)?;
                    dict.set_item("strike_time", &opt.strike_time)?;
                    if let Some(ts) = opt.strike_timestamp {
                        dict.set_item("strike_timestamp", ts)?;
                    }
                }
                if let Some(ref fut) = info.future_ex_data {
                    dict.set_item("last_trade_time", &fut.last_trade_time)?;
                    if let Some(ts) = fut.last_trade_timestamp {
                        dict.set_item("last_trade_timestamp", ts)?;
                    }
                    dict.set_item("is_main_contract", fut.is_main_contract)?;
                }
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_owner_plate ──────────────────────────────────────────
    /// Get owner plates (sectors) for securities.
    /// Returns list of dicts with security and plate_info_list.
    fn get_owner_plate(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_owner_plate(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get owner plate failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for owner in s2c.owner_plate_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", owner.security.market)?;
                dict.set_item("code", &owner.security.code)?;
                dict.set_item("name", owner.name.as_deref())?;

                let plates = pyo3::types::PyList::empty_bound(py);
                for plate in &owner.plate_info_list {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("plate_market", plate.plate.market)?;
                    d.set_item("plate_code", &plate.plate.code)?;
                    d.set_item("plate_name", &plate.name)?;
                    d.set_item("plate_type", plate.plate_type)?;
                    plates.append(d)?;
                }
                dict.set_item("plate_info_list", plates)?;

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_option_chain ─────────────────────────────────────────
    /// Get option chain for an underlying security.
    /// Returns list of dicts with strike_time and option items.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (owner_market, owner_code, begin_time, end_time, option_type=None, condition=None, index_option_type=None))]
    fn get_option_chain(
        &self,
        py: Python<'_>,
        owner_market: i32,
        owner_code: String,
        begin_time: String,
        end_time: String,
        option_type: Option<i32>,
        condition: Option<i32>,
        index_option_type: Option<i32>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_option_chain(
                    client, owner_market, owner_code,
                    begin_time, end_time,
                    option_type, condition, index_option_type, None,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get option chain failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for chain in s2c.option_chain {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("strike_time", &chain.strike_time)?;
                dict.set_item("strike_timestamp", chain.strike_timestamp)?;

                let options = pyo3::types::PyList::empty_bound(py);
                for item in &chain.option {
                    let d = pyo3::types::PyDict::new_bound(py);
                    if let Some(ref call) = item.call {
                        let cd = pyo3::types::PyDict::new_bound(py);
                        cd.set_item("market", call.basic.security.market)?;
                        cd.set_item("code", &call.basic.security.code)?;
                        cd.set_item("name", &call.basic.name)?;
                        cd.set_item("lot_size", call.basic.lot_size)?;
                        cd.set_item("sec_type", call.basic.sec_type)?;
                        if let Some(ref opt) = call.option_ex_data {
                            cd.set_item("strike_price", opt.strike_price)?;
                            cd.set_item("strike_time", &opt.strike_time)?;
                            cd.set_item("option_type", opt.r#type)?;
                        }
                        d.set_item("call", cd)?;
                    }
                    if let Some(ref put) = item.put {
                        let pd = pyo3::types::PyDict::new_bound(py);
                        pd.set_item("market", put.basic.security.market)?;
                        pd.set_item("code", &put.basic.security.code)?;
                        pd.set_item("name", &put.basic.name)?;
                        pd.set_item("lot_size", put.basic.lot_size)?;
                        pd.set_item("sec_type", put.basic.sec_type)?;
                        if let Some(ref opt) = put.option_ex_data {
                            pd.set_item("strike_price", opt.strike_price)?;
                            pd.set_item("strike_time", &opt.strike_time)?;
                            pd.set_item("option_type", opt.r#type)?;
                        }
                        d.set_item("put", pd)?;
                    }
                    options.append(d)?;
                }
                dict.set_item("option_list", options)?;

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_warrant ──────────────────────────────────────────────
    /// Get warrant list.
    /// Returns a dict with last_page, all_count, and data list.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (begin, num, sort_field, ascend, owner=None, type_list=None, issuer_list=None))]
    fn get_warrant(
        &self,
        py: Python<'_>,
        begin: i32,
        num: i32,
        sort_field: i32,
        ascend: bool,
        owner: Option<(i32, String)>,
        type_list: Option<Vec<i32>>,
        issuer_list: Option<Vec<i32>>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_warrant(
                    client, begin, num, sort_field, ascend,
                    owner, type_list.unwrap_or_default(), issuer_list.unwrap_or_default(),
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get warrant failed: {}", e)))?;

        let result = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            result.set_item("last_page", s2c.last_page)?;
            result.set_item("all_count", s2c.all_count)?;

            let data_list = pyo3::types::PyList::empty_bound(py);
            for w in &s2c.warrant_data_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("stock_market", w.stock.market)?;
                d.set_item("stock_code", &w.stock.code)?;
                d.set_item("owner_market", w.owner.market)?;
                d.set_item("owner_code", &w.owner.code)?;
                d.set_item("type", w.r#type)?;
                d.set_item("issuer", w.issuer)?;
                d.set_item("name", &w.name)?;
                d.set_item("maturity_time", &w.maturity_time)?;
                d.set_item("maturity_timestamp", w.maturity_timestamp)?;
                d.set_item("list_time", &w.list_time)?;
                d.set_item("list_timestamp", w.list_timestamp)?;
                d.set_item("last_trade_time", &w.last_trade_time)?;
                d.set_item("last_trade_timestamp", w.last_trade_timestamp)?;
                d.set_item("recovery_price", w.recovery_price)?;
                d.set_item("strike_price", w.strike_price)?;
                d.set_item("cur_price", w.cur_price)?;
                d.set_item("last_close_price", w.last_close_price)?;
                d.set_item("price_change_val", w.price_change_val)?;
                d.set_item("change_rate", w.change_rate)?;
                d.set_item("volume", w.volume)?;
                d.set_item("turnover", w.turnover)?;
                d.set_item("premium", w.premium)?;
                d.set_item("break_even_point", w.break_even_point)?;
                d.set_item("conversion_ratio", w.conversion_ratio)?;
                d.set_item("conversion_price", w.conversion_price)?;
                d.set_item("lot_size", w.lot_size)?;
                d.set_item("leverage", w.leverage)?;
                d.set_item("ipop", w.ipop)?;
                d.set_item("effective_leverage", w.effective_leverage)?;
                d.set_item("score", w.score)?;
                d.set_item("status", w.status)?;
                d.set_item("bid_price", w.bid_price)?;
                d.set_item("ask_price", w.ask_price)?;
                d.set_item("bid_vol", w.bid_vol)?;
                d.set_item("ask_vol", w.ask_vol)?;
                d.set_item("high_price", w.high_price)?;
                d.set_item("low_price", w.low_price)?;
                d.set_item("implied_volatility", w.implied_volatility)?;
                d.set_item("delta", w.delta)?;
                d.set_item("street_rate", w.street_rate)?;
                d.set_item("street_vol", w.street_vol)?;
                d.set_item("amplitude", w.amplitude)?;
                d.set_item("issue_size", w.issue_size)?;
                d.set_item("upper_strike_price", w.upper_strike_price)?;
                d.set_item("lower_strike_price", w.lower_strike_price)?;
                d.set_item("in_line_price_status", w.in_line_price_status)?;
                d.set_item("price_recovery_ratio", w.price_recovery_ratio)?;
                data_list.append(d)?;
            }
            result.set_item("data", data_list)?;
        }
        Ok(result.into_any().unbind())
    }

    // ── Quote: get_capital_flow ──────────────────────────────────────────
    /// Get capital flow for a single security.
    /// Returns a dict with flow_item_list.
    #[pyo3(signature = (market, code, period_type=None))]
    fn get_capital_flow(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
        period_type: Option<i32>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_capital_flow(client, market, code, period_type).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get capital flow failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("last_valid_time", s2c.last_valid_time.as_deref())?;
            dict.set_item("last_valid_timestamp", s2c.last_valid_timestamp)?;

            let flow_list = pyo3::types::PyList::empty_bound(py);
            for item in &s2c.flow_item_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("in_flow", item.in_flow)?;
                d.set_item("time", item.time.as_deref())?;
                d.set_item("timestamp", item.timestamp)?;
                d.set_item("main_in_flow", item.main_in_flow)?;
                d.set_item("super_in_flow", item.super_in_flow)?;
                d.set_item("big_in_flow", item.big_in_flow)?;
                d.set_item("mid_in_flow", item.mid_in_flow)?;
                d.set_item("sml_in_flow", item.sml_in_flow)?;
                flow_list.append(d)?;
            }
            dict.set_item("flow_item_list", flow_list)?;
        }
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_capital_distribution ──────────────────────────────────
    /// Get capital distribution for a single security.
    /// Returns a dict with capital in/out fields.
    fn get_capital_distribution(
        &self,
        py: Python<'_>,
        market: i32,
        code: String,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_capital_distribution(client, market, code).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get capital distribution failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("capital_in_big", s2c.capital_in_big)?;
            dict.set_item("capital_in_mid", s2c.capital_in_mid)?;
            dict.set_item("capital_in_small", s2c.capital_in_small)?;
            dict.set_item("capital_out_big", s2c.capital_out_big)?;
            dict.set_item("capital_out_mid", s2c.capital_out_mid)?;
            dict.set_item("capital_out_small", s2c.capital_out_small)?;
            dict.set_item("update_time", s2c.update_time.as_deref())?;
            dict.set_item("update_timestamp", s2c.update_timestamp)?;
            dict.set_item("capital_in_super", s2c.capital_in_super)?;
            dict.set_item("capital_out_super", s2c.capital_out_super)?;
        }
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_user_security ────────────────────────────────────────
    /// Get user security group.
    /// Returns list of static info dicts.
    fn get_user_security(
        &self,
        py: Python<'_>,
        group_name: String,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_user_security(client, group_name).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get user security failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.static_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                let basic = &info.basic;
                let sec = &basic.security;
                dict.set_item("market", sec.market)?;
                dict.set_item("code", &sec.code)?;
                dict.set_item("name", &basic.name)?;
                dict.set_item("lot_size", basic.lot_size)?;
                dict.set_item("sec_type", basic.sec_type)?;
                dict.set_item("list_time", &basic.list_time)?;
                if let Some(exch_type) = basic.exch_type {
                    dict.set_item("exch_type", exch_type)?;
                }
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: modify_user_security ─────────────────────────────────────
    /// Modify user security group.
    /// Returns an empty dict (S2C has no fields).
    fn modify_user_security(
        &self,
        py: Python<'_>,
        group_name: String,
        op: i32,
        securities: Vec<(i32, String)>,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::modify_user_security(client, group_name, op, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Modify user security failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        Ok(dict.into_any().unbind())
    }

    // ── Quote: get_code_change ──────────────────────────────────────────
    /// Get code change info for securities.
    /// Returns list of dicts with code change details.
    #[pyo3(signature = (securities, type_list=None))]
    fn get_code_change(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
        type_list: Option<Vec<i32>>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_code_change(
                    client, securities, type_list.unwrap_or_default(),
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get code change failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.code_change_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("type", info.r#type)?;
                dict.set_item("market", info.security.market)?;
                dict.set_item("code", &info.security.code)?;
                dict.set_item("related_market", info.related_security.market)?;
                dict.set_item("related_code", &info.related_security.code)?;
                dict.set_item("public_time", info.public_time.as_deref())?;
                dict.set_item("public_timestamp", info.public_timestamp)?;
                dict.set_item("effective_time", info.effective_time.as_deref())?;
                dict.set_item("effective_timestamp", info.effective_timestamp)?;
                dict.set_item("end_time", info.end_time.as_deref())?;
                dict.set_item("end_timestamp", info.end_timestamp)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_ipo_list ─────────────────────────────────────────────
    /// Get IPO list for a market.
    /// Returns list of dicts with IPO data.
    fn get_ipo_list(
        &self,
        py: Python<'_>,
        market: i32,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_ipo_list(client, market).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get IPO list failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for ipo in s2c.ipo_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("market", ipo.basic.security.market)?;
                dict.set_item("code", &ipo.basic.security.code)?;
                dict.set_item("name", &ipo.basic.name)?;
                dict.set_item("list_time", ipo.basic.list_time.as_deref())?;
                dict.set_item("list_timestamp", ipo.basic.list_timestamp)?;

                if let Some(ref hk) = ipo.hk_ex_data {
                    dict.set_item("ipo_price_min", hk.ipo_price_min)?;
                    dict.set_item("ipo_price_max", hk.ipo_price_max)?;
                    dict.set_item("list_price", hk.list_price)?;
                    dict.set_item("lot_size", hk.lot_size)?;
                    dict.set_item("entrance_price", hk.entrance_price)?;
                    dict.set_item("is_subscribe_status", hk.is_subscribe_status)?;
                }
                if let Some(ref us) = ipo.us_ex_data {
                    dict.set_item("ipo_price_min", us.ipo_price_min)?;
                    dict.set_item("ipo_price_max", us.ipo_price_max)?;
                    dict.set_item("issue_size", us.issue_size)?;
                }
                if let Some(ref cn) = ipo.cn_ex_data {
                    dict.set_item("apply_code", &cn.apply_code)?;
                    dict.set_item("issue_size", cn.issue_size)?;
                    dict.set_item("ipo_price", cn.ipo_price)?;
                    dict.set_item("winning_ratio", cn.winning_ratio)?;
                }

                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_future_info ──────────────────────────────────────────
    /// Get future info for securities.
    /// Returns list of dicts with future contract details.
    fn get_future_info(
        &self,
        py: Python<'_>,
        securities: Vec<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_future_info(client, securities).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get future info failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for info in s2c.future_info_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("name", &info.name)?;
                dict.set_item("market", info.security.market)?;
                dict.set_item("code", &info.security.code)?;
                dict.set_item("last_trade_time", &info.last_trade_time)?;
                dict.set_item("last_trade_timestamp", info.last_trade_timestamp)?;
                if let Some(ref owner) = info.owner {
                    dict.set_item("owner_market", owner.market)?;
                    dict.set_item("owner_code", &owner.code)?;
                }
                dict.set_item("owner_other", &info.owner_other)?;
                dict.set_item("exchange", &info.exchange)?;
                dict.set_item("contract_type", &info.contract_type)?;
                dict.set_item("contract_size", info.contract_size)?;
                dict.set_item("contract_size_unit", &info.contract_size_unit)?;
                dict.set_item("quote_currency", &info.quote_currency)?;
                dict.set_item("min_var", info.min_var)?;
                dict.set_item("min_var_unit", &info.min_var_unit)?;
                dict.set_item("quote_unit", info.quote_unit.as_deref())?;
                dict.set_item("time_zone", &info.time_zone)?;
                dict.set_item("exchange_format_url", &info.exchange_format_url)?;
                if let Some(ref origin) = info.origin {
                    dict.set_item("origin_market", origin.market)?;
                    dict.set_item("origin_code", &origin.code)?;
                }
                // trade_time is a repeated TradeTime array
                let times = pyo3::types::PyList::empty_bound(py);
                for tt in &info.trade_time {
                    let td = pyo3::types::PyDict::new_bound(py);
                    td.set_item("begin", tt.begin)?;
                    td.set_item("end", tt.end)?;
                    times.append(td)?;
                }
                dict.set_item("trade_time", times)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: request_trade_date ───────────────────────────────────────
    /// Request trade dates for a market.
    /// Returns list of dicts with trade date info.
    #[pyo3(signature = (market, begin_time, end_time, security=None))]
    fn request_trade_date(
        &self,
        py: Python<'_>,
        market: i32,
        begin_time: String,
        end_time: String,
        security: Option<(i32, String)>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::request_trade_date(
                    client, market, begin_time, end_time, security,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Request trade date failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for td in s2c.trade_date_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("time", &td.time)?;
                dict.set_item("timestamp", td.timestamp)?;
                dict.set_item("trade_date_type", td.trade_date_type)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Quote: get_option_expiration_date ────────────────────────────────
    /// Get option expiration dates for an underlying security.
    /// Returns list of dicts with expiration date info.
    #[pyo3(signature = (owner_market, owner_code, index_option_type=None))]
    fn get_option_expiration_date(
        &self,
        py: Python<'_>,
        owner_market: i32,
        owner_code: String,
        index_option_type: Option<i32>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::snapshot::get_option_expiration_date(
                    client, owner_market, owner_code, index_option_type,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get option expiration date failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for date in s2c.date_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("strike_time", date.strike_time.as_deref())?;
                dict.set_item("strike_timestamp", date.strike_timestamp)?;
                dict.set_item("option_expiry_date_distance", date.option_expiry_date_distance)?;
                dict.set_item("cycle", date.cycle)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get global state from Futu OpenD (proto 1002).
    /// Returns a dict with market states and connection info.
    fn get_global_state(&self, py: Python<'_>) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let user_id = client.init_response()
            .map(|r| r.login_user_id)
            .unwrap_or(0);

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::client::init::get_global_state(client, user_id).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get global state failed: {}", e)))?;

        let dict = pyo3::types::PyDict::new_bound(py);
        if let Some(s2c) = response.s2c {
            dict.set_item("market_hk", s2c.market_hk)?;
            dict.set_item("market_us", s2c.market_us)?;
            dict.set_item("market_sh", s2c.market_sh)?;
            dict.set_item("market_sz", s2c.market_sz)?;
            dict.set_item("market_hk_future", s2c.market_hk_future)?;
            dict.set_item("market_us_future", s2c.market_us_future)?;
            dict.set_item("market_sg_future", s2c.market_sg_future)?;
            dict.set_item("market_jp_future", s2c.market_jp_future)?;
            dict.set_item("qot_logined", s2c.qot_logined)?;
            dict.set_item("trd_logined", s2c.trd_logined)?;
            dict.set_item("server_ver", s2c.server_ver)?;
            dict.set_item("server_build_no", s2c.server_build_no)?;
            dict.set_item("time", s2c.time)?;
            dict.set_item("local_time", s2c.local_time)?;
        }
        Ok(dict.into_any().unbind())
    }
}

/// Convert a K-line proto into the dict shape shared by `get_history_kl` / `get_kl`.
fn kline_to_dict(py: Python<'_>, kl: &crate::generated::qot_common::KLine) -> PyResult<PyObject> {
    let dict = pyo3::types::PyDict::new_bound(py);
    dict.set_item("time", &kl.time)?;
    dict.set_item("is_blank", kl.is_blank)?;
    dict.set_item("open_price", kl.open_price)?;
    dict.set_item("high_price", kl.high_price)?;
    dict.set_item("low_price", kl.low_price)?;
    dict.set_item("close_price", kl.close_price)?;
    dict.set_item("last_close_price", kl.last_close_price)?;
    dict.set_item("volume", kl.volume)?;
    dict.set_item("turnover", kl.turnover)?;
    dict.set_item("timestamp", kl.timestamp)?;
    Ok(dict.into_any().unbind())
}
