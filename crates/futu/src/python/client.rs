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
                dict.set_item("cur_price", qot.cur_price)?;
                dict.set_item("open_price", qot.open_price)?;
                dict.set_item("high_price", qot.high_price)?;
                dict.set_item("low_price", qot.low_price)?;
                dict.set_item("last_close_price", qot.last_close_price)?;
                dict.set_item("volume", qot.volume)?;
                dict.set_item("turnover", qot.turnover)?;
                dict.set_item("update_timestamp", qot.update_timestamp)?;
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

    /// Filter stocks by conditions (Qot_StockFilter, proto 3215).
    /// base_filters: list of (fieldName, filterMin, filterMax, sortDir)
    /// accumulate_filters: list of (fieldName, days, filterMin, filterMax, sortDir)
    /// financial_filters: list of (fieldName, quarter, filterMin, filterMax, sortDir)
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
    #[pyo3(signature = (trd_env, acc_id, trd_market, filter_status_list=None))]
    fn get_history_order_list(
        &self,
        py: Python<'_>,
        trd_env: i32,
        acc_id: u64,
        trd_market: i32,
        filter_status_list: Option<Vec<i32>>,
    ) -> PyResult<Vec<PyObject>> {
        let client = self.get_client()?;
        let client = &*client;

        let response = py.allow_threads(|| {
            self.runtime.block_on(async {
                crate::trade::query::get_history_order_list(
                    client, trd_env, acc_id, trd_market, None,
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
                result.push(dict.into_any().unbind());
            }
        }
        Ok(result)
    }

    // ── Trade: get_history_order_fill_list ───────────────────────────────
    /// Get historical order fill list.
    /// Returns list of dicts with fill details.
    fn get_history_order_fill_list(
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
                crate::trade::query::get_history_order_fill_list(
                    client, trd_env, acc_id, trd_market, None,
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
                d.set_item("strike_price", w.strike_price)?;
                d.set_item("cur_price", w.cur_price)?;
                d.set_item("last_close_price", w.last_close_price)?;
                d.set_item("volume", w.volume)?;
                d.set_item("turnover", w.turnover)?;
                d.set_item("premium", w.premium)?;
                d.set_item("conversion_ratio", w.conversion_ratio)?;
                d.set_item("lot_size", w.lot_size)?;
                d.set_item("leverage", w.leverage)?;
                d.set_item("effective_leverage", w.effective_leverage)?;
                d.set_item("score", w.score)?;
                d.set_item("status", w.status)?;
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
                dict.set_item("time_zone", &info.time_zone)?;
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
