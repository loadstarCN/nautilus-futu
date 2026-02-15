#![allow(clippy::useless_conversion)]

use std::sync::Arc;
use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use parking_lot::Mutex as SyncMutex;
use tokio::runtime::Runtime;
use tokio::sync::{mpsc, Mutex};

use crate::config::FutuConfig;
use crate::client::FutuClient;

type PushMessage = (u32, Vec<u8>);
type PushSender = mpsc::UnboundedSender<PushMessage>;
type PushReceiver = Arc<Mutex<mpsc::UnboundedReceiver<PushMessage>>>;

/// Python-facing Futu client.
///
/// All `#[pymethods]` take `&self` (not `&mut self`) to avoid PyO3's internal
/// RefCell exclusive borrow.  Mutable state is guarded by `SyncMutex` and the
/// lock is never held across `py.allow_threads()` boundaries.
#[pyclass]
pub struct PyFutuClient {
    runtime: Runtime,
    client: SyncMutex<Option<Arc<FutuClient>>>,
    push_tx: SyncMutex<Option<PushSender>>,
    push_rx: SyncMutex<Option<PushReceiver>>,
    push_handles: SyncMutex<Vec<tokio::task::JoinHandle<()>>>,
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
            push_tx: SyncMutex::new(None),
            push_rx: SyncMutex::new(None),
            push_handles: SyncMutex::new(Vec::new()),
        })
    }

    /// Connect to Futu OpenD gateway.
    fn connect(
        &self,
        py: Python<'_>,
        host: &str,
        port: u16,
        client_id: &str,
        client_ver: i32,
    ) -> PyResult<()> {
        let config = FutuConfig {
            host: host.to_string(),
            port,
            client_id: client_id.to_string(),
            client_ver,
            ..Default::default()
        };

        // Release the GIL during blocking network operations.
        // No SyncMutex is held here — only `self.runtime` (immutable) is accessed.
        let client = py.allow_threads(|| {
            let mut client = self.runtime.block_on(async {
                FutuClient::connect(config).await
            }).map_err(|e| e.to_string())?;

            self.runtime.block_on(async {
                client.init().await
            }).map_err(|e| e.to_string())?;

            Ok::<_, String>(client)
        }).map_err(|e| PyRuntimeError::new_err(format!("Connection failed: {}", e)))?;

        // Brief lock to store the connected client
        *self.client.lock() = Some(Arc::new(client));
        Ok(())
    }

    /// Disconnect from Futu OpenD.
    fn disconnect(&self, _py: Python<'_>) -> PyResult<()> {
        // Abort push forwarder tasks
        for handle in self.push_handles.lock().drain(..) {
            handle.abort();
        }
        *self.push_tx.lock() = None;
        *self.push_rx.lock() = None;

        // Take the Arc out — when the last Arc reference is dropped,
        // FutuClient::drop() aborts keepalive and recv handles.
        let _client = self.client.lock().take();
        tracing::info!("Disconnected from Futu OpenD");
        Ok(())
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
                d.set_item("order_count", ob.oreder_count)?;
                asks.append(d)?;
            }
            dict.set_item("asks", asks)?;

            let bids = pyo3::types::PyList::empty_bound(py);
            for ob in &s2c.order_book_bid_list {
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("price", ob.price)?;
                d.set_item("volume", ob.volume)?;
                d.set_item("order_count", ob.oreder_count)?;
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
                    dict.set_item("time", ts)?;
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
                dict.set_item("cur_price", qot.cur_price)?;
                dict.set_item("open_price", qot.open_price)?;
                dict.set_item("high_price", qot.high_price)?;
                dict.set_item("low_price", qot.low_price)?;
                dict.set_item("last_close_price", qot.last_close_price)?;
                dict.set_item("volume", qot.volume)?;
                dict.set_item("turnover", qot.turnover)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get historical K-line data.
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

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::quote::history::get_history_kl(
                    client, market, code, rehab_type, kl_type,
                    begin_time, end_time, max_count,
                ).await
            }).map_err(|e| e.to_string())
        }).map_err(|e| PyRuntimeError::new_err(format!("Get history KL failed: {}", e)))?;

        let mut result = Vec::new();
        if let Some(s2c) = response.s2c {
            for kl in s2c.kl_list {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("time", &kl.time)?;
                dict.set_item("is_blank", kl.is_blank)?;
                dict.set_item("open_price", kl.open_price)?;
                dict.set_item("high_price", kl.high_price)?;
                dict.set_item("low_price", kl.low_price)?;
                dict.set_item("close_price", kl.close_price)?;
                dict.set_item("volume", kl.volume)?;
                dict.set_item("turnover", kl.turnover)?;
                dict.set_item("timestamp", kl.timestamp)?;
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    /// Get account list.
    fn get_acc_list(&self, py: Python<'_>) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let user_id = client.init_response()
            .map(|r| r.login_user_id)
            .unwrap_or(0);

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::account::get_acc_list(client, user_id).await
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
                dict.set_item("security_firm", acc.security_firm)?;
                dict.set_item("sim_acc_type", acc.sim_acc_type)?;
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
    /// sec_market: 1=HK, 2=US, 3=CN_SH, 4=CN_SZ, etc.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (trd_env, acc_id, trd_market, trd_side, order_type, code, qty, price=None, sec_market=None))]
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
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::order::place_order(
                    client, trd_env, acc_id, trd_market,
                    trd_side, order_type, code, qty, price,
                    None, sec_market, None, None, None, None, None, None, None,
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
    #[pyo3(signature = (trd_env, acc_id, trd_market, order_id, modify_op, qty=None, price=None))]
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
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::order::modify_order(
                    client, trd_env, acc_id, trd_market,
                    order_id, modify_op, qty, price, None,
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
    fn get_funds(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
    ) -> PyResult<PyObject> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_funds(client, trd_env, acc_id, trd_market).await
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

    /// Check if the client is connected to Futu OpenD.
    fn is_connected(&self) -> bool {
        self.client.lock().is_some()
    }

    /// Start receiving push notifications for the given proto_ids.
    /// First call creates the merged channel; subsequent calls reuse it
    /// and only add new forwarder tasks (append mode).
    fn start_push(
        &self,
        py: Python<'_>,
        proto_ids: Vec<u32>,
    ) -> PyResult<()> {
        let client = self.get_client()?;
        let client = &*client;

        // Reuse existing tx/rx if already created, otherwise create new pair
        let tx = {
            let mut tx_guard = self.push_tx.lock();
            if let Some(ref tx) = *tx_guard {
                tx.clone()
            } else {
                let (tx, rx) = mpsc::unbounded_channel::<PushMessage>();
                *tx_guard = Some(tx.clone());
                *self.push_rx.lock() = Some(Arc::new(Mutex::new(rx)));
                tx
            }
        };

        // For each proto_id, register a push handler and spawn a forwarder task
        for proto_id in proto_ids {
            let mut push_rx = py.allow_threads(|| {
                self.runtime.block_on(async {
                    client.subscribe_push(proto_id).await
                })
            });

            let tx_clone = tx.clone();
            let handle = self.runtime.spawn(async move {
                while let Some(msg) = push_rx.recv().await {
                    if tx_clone.send((msg.proto_id, msg.body)).is_err() {
                        break;
                    }
                }
            });
            self.push_handles.lock().push(handle);
        }

        Ok(())
    }

    /// Poll for the next push message. Returns a dict or None on timeout.
    /// timeout_ms: how long to wait for a message (in milliseconds)
    #[pyo3(signature = (timeout_ms=100))]
    fn poll_push(
        &self,
        py: Python<'_>,
        timeout_ms: u64,
    ) -> PyResult<Option<PyObject>> {
        let rx = match self.push_rx.lock().as_ref() {
            Some(rx) => Arc::clone(rx),
            None => return Ok(None),
        };

        let timeout = std::time::Duration::from_millis(timeout_ms);

        let result = py.allow_threads(|| {
            self.runtime.block_on(async {
                let mut guard = rx.lock().await;
                tokio::time::timeout(timeout, guard.recv()).await
            })
        });

        match result {
            Ok(Some((proto_id, body))) => {
                let data = super::push_decode::decode_push_message(py, proto_id, &body)?;
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("proto_id", proto_id)?;
                dict.set_item("data", data)?;
                Ok(Some(dict.into_any().unbind()))
            }
            Ok(None) => {
                // Channel closed
                Ok(None)
            }
            Err(_) => {
                // Timeout — no message available
                Ok(None)
            }
        }
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
            dict.set_item("market_cn", s2c.market_cn)?;
            dict.set_item("market_hk_future", s2c.market_hk_future)?;
            dict.set_item("market_us_future", s2c.market_us_future)?;
            dict.set_item("market_sg", s2c.market_sg)?;
            dict.set_item("market_jp", s2c.market_jp)?;
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
