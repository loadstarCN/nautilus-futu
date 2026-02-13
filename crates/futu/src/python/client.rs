#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use tokio::runtime::Runtime;

use crate::config::FutuConfig;
use crate::client::FutuClient;

/// Python-facing Futu client.
#[pyclass]
pub struct PyFutuClient {
    runtime: Runtime,
    client: Option<FutuClient>,
}

#[pymethods]
impl PyFutuClient {
    #[new]
    fn new() -> PyResult<Self> {
        let runtime = Runtime::new()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to create runtime: {}", e)))?;
        Ok(Self {
            runtime,
            client: None,
        })
    }

    /// Connect to Futu OpenD gateway.
    fn connect(
        &mut self,
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

        // Release the GIL during blocking network operations
        let client = py.allow_threads(|| {
            let mut client = self.runtime.block_on(async {
                FutuClient::connect(config).await
            }).map_err(|e| e.to_string())?;

            self.runtime.block_on(async {
                client.init().await
            }).map_err(|e| e.to_string())?;

            Ok::<_, String>(client)
        }).map_err(|e| PyRuntimeError::new_err(format!("Connection failed: {}", e)))?;

        self.client = Some(client);
        Ok(())
    }

    /// Disconnect from Futu OpenD.
    fn disconnect(&mut self, py: Python<'_>) -> PyResult<()> {
        if let Some(mut client) = self.client.take() {
            py.allow_threads(|| {
                self.runtime.block_on(async {
                    client.disconnect().await;
                });
            });
        }
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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
        let client = self.client.as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Not connected"))?;

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
}
