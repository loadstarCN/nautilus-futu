# NautilusTrader ↔ Futu OpenD 完整任务清单

> 基于 NautilusTrader 适配器参考（Binance/IB/Bybit/dYdX）和 Futu OpenD API 文档逐一对照生成。
> 标注 ✅ = 已实现 | ⚠️ = 部分实现 | ❌ = 未实现 | 🚫 = Futu 不支持

---

## 一、实现状态总览

| 功能域 | 已完成 | 部分 | 未完成 | 不支持 |
|--------|--------|------|--------|--------|
| PyO3 绑定 | 11 | 0 | 7+ | 0 |
| DataClient | 6 | 3 | 5 | 0 |
| ExecClient | 5 | 0 | 8 | 0 |
| InstrumentProvider | 2 | 1 | 2 | 0 |
| 推送链路 | 0 | 0 | 6 | 0 |
| Rust 新增函数 | 0 | 0 | 11 | 0 |
| 基础设施 | 2 | 0 | 4 | 0 |

---

## 二、PyO3 绑定层（优先级：P0 — 阻塞所有下游任务）

所有 Python 功能依赖 `python/client.rs` 的 `PyFutuClient` 暴露方法。

### 已暴露 ✅

| PyO3 方法 | Rust 函数 | Proto ID |
|-----------|-----------|----------|
| `connect()` | `FutuClient::connect` + `init` | 1001 |
| `disconnect()` | `FutuClient::disconnect` | - |
| `subscribe()` | `quote::subscribe` | 3001 |
| `get_static_info()` | `quote::get_static_info` | 3202 |
| `get_basic_qot()` | `quote::get_basic_qot` | 3004 |
| `get_history_kl()` | `quote::get_history_kl` | 3103 |
| `get_acc_list()` | `trade::get_acc_list` | 2001 |
| `unlock_trade()` | `trade::unlock_trade` | 2005 |
| `place_order()` | `trade::place_order` | 2202 |
| `modify_order()` | `trade::modify_order` | 2205 |

### 需要新增 ❌

| # | PyO3 方法 | Rust 函数 | Proto ID | 用途 | 阻塞 |
|---|-----------|-----------|----------|------|------|
| P0-1 | `get_order_list()` | `trade::query::get_order_list` | 2201 | generate_order_status_report | ExecClient 报告 |
| P0-2 | `get_order_fill_list()` | `trade::query::get_order_fill_list` | 2211 | generate_fill_reports | ExecClient 报告 |
| P0-3 | `get_position_list()` | `trade::query::get_position_list` | 2102 | generate_position_status_reports | ExecClient 报告 |
| P0-4 | `get_funds()` | `trade::query::get_funds` | 2101 | 账户余额/保证金查询 | AccountState 事件 |
| P0-5 | `get_security_snapshot()` | `quote::get_security_snapshot` | 3203 | 行情快照请求 | request_quote_ticks |
| P0-6 | `poll_push()` / `register_push()` | `FutuClient::subscribe_push` | - | 接收所有推送消息 | 整条推送链路 |
| P0-7 | `get_order_book()` | 需新增 Rust 函数 | 3012 | 请求盘口数据 | request_order_book |

**实现要点**：
- P0-1/2/3/4: Rust 侧 `trade::query` 已完整实现，只需在 `PyFutuClient` 添加 `#[pyo3]` 包装，将 protobuf Response 转为 Python dict
- P0-5: Rust 侧 `quote::snapshot::get_security_snapshot` 已实现
- P0-6: Rust 侧 `FutuClient::subscribe_push(proto_id)` 返回 `mpsc::UnboundedReceiver`。需设计 Python 侧接口：
  - 方案 A（推荐）：`poll_push(timeout_ms) -> list[dict]` — 阻塞轮询，Python 端在后台线程调用
  - 方案 B：`register_callback(proto_id, callable)` — Rust 侧持有 Python 回调，在 recv loop 中调用
- P0-7: 需在 Rust 侧 `quote/` 新增 `get_order_book()` 函数（protobuf `qot_get_order_book` 已生成）

---

## 三、推送链路（优先级：P1 — 核心实时能力）

当前所有订阅只发送 subscribe 请求给 Futu OpenD，但**不接收推送消息**。需要打通完整链路：

```
Futu OpenD → TCP → Rust Dispatcher → PyO3 poll_push → Python 回调 → msgbus 发布
```

### 行情推送

| # | 推送类型 | Futu Proto ID | Futu API | NT 数据类型 | Python 回调位置 |
|---|---------|---------------|----------|------------|----------------|
| P1-1 | 实时报价推送 | 3005 | Qot_UpdateBasicQot | `QuoteTick` | `data.py` |
| P1-2 | 逐笔成交推送 | 3011 | Qot_UpdateTicker | `TradeTick` | `data.py` |
| P1-3 | 盘口推送 | 3013 | Qot_UpdateOrderBook | `OrderBookDelta` / `OrderBookDeltas` | `data.py` |
| P1-4 | K线推送 | 3007 | Qot_UpdateKL | `Bar` | `data.py` |

**Futu 推送 protobuf 结构**：
- `Qot_UpdateBasicQot.S2C`: `securityList[]{security{market,code}, ...basicQotData}` — 包含 curPrice, openPrice, highPrice, lowPrice, lastClosePrice, volume, turnover, timestamp
- `Qot_UpdateTicker.S2C`: `security{market,code}, tickerList[]{time, sequence, dir, price, volume, turnover, type}` — 逐笔明细
- `Qot_UpdateOrderBook.S2C`: `security{market,code}, orderBookAskList[]{price,volume,orederCount}, orderBookBidList[]{...}` — 10 档盘口
- `Qot_UpdateKL.S2C`: `security{market,code}, klType, klList[]{time, isBlank, highPrice, openPrice, lowPrice, closePrice, lastClosePrice, volume, turnover, timestamp}` — 对应 BarType

**实现步骤**：
1. PyO3 层暴露 `poll_push()` 方法（P0-6）
2. `data.py._connect()` 中启动后台 asyncio task 轮询推送
3. 对每条推送消息按 proto_id 分发到对应解析函数
4. 解析后通过 `self._handle_data(data)` 发布到 msgbus

### 交易推送

| # | 推送类型 | Futu Proto ID | Futu API | NT 事件类型 | Python 回调位置 |
|---|---------|---------------|----------|------------|----------------|
| P1-5 | 订单状态推送 | 2208 | Trd_UpdateOrder | `OrderAccepted` / `OrderCanceled` / `OrderFilled` 等 | `execution.py` |
| P1-6 | 成交推送 | 2218 | Trd_UpdateOrderFill | `OrderFilled` | `execution.py` |

**Futu 推送 protobuf 结构**：
- `Trd_UpdateOrder.S2C`: `header{trdEnv,accID,trdMarketAuthList}, order{trdSide,orderType,orderStatus,orderID,code,name,qty,price,createTime,updateTime,fillQty,fillAvgPrice,...}` — 完整订单快照
- `Trd_UpdateOrderFill.S2C`: `header{...}, orderFill{trdSide,fillID,orderID,code,name,qty,price,createTime,counterBrokerID,...}` — 成交明细

**前置条件**：需先调用 `Trd_SubAccPush`(2008) 订阅账户推送，Futu 才会推送 2208/2218

**Rust 侧需新增**：
- `trade/push.rs`: `sub_acc_push()` 函数（protobuf `trd_sub_acc_push` 已生成）
- PyO3 暴露 `sub_acc_push()` 方法

**订单状态映射** (Futu OrderStatus → NT 事件)：

| Futu OrderStatus | 值 | NT 事件 |
|------------------|----|---------|
| SUBMITTING (0) | 0 | OrderSubmitted |
| SUBMITTED (1) | 1 | OrderAccepted |
| FILLED_PART (2) | 2 | OrderFilled (partial) |
| FILLED_ALL (3) | 3 | OrderFilled (full) |
| CANCELLING (4) | 4 | (等待中) |
| CANCELLED_PART (5) | 5 | OrderCanceled (partial) |
| CANCELLED_ALL (6) | 6 | OrderCanceled |
| FAILED (7) | 7 | OrderRejected |
| DISABLED (8) | 8 | OrderCanceled |
| DELETED (9) | 9 | OrderCanceled |

---

## 四、DataClient 方法 (`data.py`)

### 连接/断开

| # | NT 方法 | 状态 | 说明 |
|---|---------|------|------|
| - | `_connect()` | ✅ | 连接 Futu OpenD |
| - | `_disconnect()` | ✅ | 断开连接 |

### 订阅类

| # | NT 方法 | 状态 | Futu API | 说明 |
|---|---------|------|----------|------|
| - | `_subscribe_quote_ticks()` | ⚠️ | Qot_Sub(3001) SUB_TYPE_BASIC=1 | 发送订阅请求 ✅，接收推送 ❌ |
| - | `_subscribe_trade_ticks()` | ⚠️ | Qot_Sub(3001) SUB_TYPE_TICKER=4 | 发送订阅请求 ✅，接收推送 ❌ |
| - | `_subscribe_order_book_deltas()` | ⚠️ | Qot_Sub(3001) SUB_TYPE_ORDER_BOOK=2 | 发送订阅请求 ✅，接收推送 ❌，解析 ❌ |
| - | `_subscribe_bars()` | ⚠️ | Qot_Sub(3001) SUB_TYPE_KL_*=6-11 | 发送订阅请求 ✅，接收推送 ❌ |
| D-1 | `_unsubscribe_order_book_deltas()` | ❌ | Qot_Sub(3001) is_sub=False | 需新增 |
| D-2 | `_unsubscribe_bars()` | ❌ | Qot_Sub(3001) is_sub=False | 需新增 |

### 请求类（拉取历史/快照数据）

| # | NT 方法 | 状态 | Futu API | Proto ID | 说明 |
|---|---------|------|----------|----------|------|
| - | `_request_bars()` | ✅ | Qot_RequestHistoryKL | 3103 | 历史K线 |
| D-3 | `_request_instrument()` | ❌ | Qot_GetStaticInfo | 3202 | 请求单个证券信息 → cache |
| D-4 | `_request_quote_ticks()` | ❌ | Qot_GetBasicQot | 3004 | 请求当前报价快照 |
| D-5 | `_request_trade_ticks()` | ❌ | Qot_GetTicker | 3010 | 请求最近逐笔列表（最多1000条） |

**解析函数需新增** (`parsing/market_data.py`)：
- `parse_futu_order_book()` — 将 Futu orderBookAskList/orderBookBidList → `OrderBookDelta` 列表
- `parse_futu_update_quote()` — 将推送的 BasicQot → `QuoteTick`（现有 `parse_futu_quote_tick` 可复用）
- `parse_futu_update_ticker()` — 将推送的 TickerList → `TradeTick` 列表
- `parse_futu_update_kl()` — 将推送的 KL → `Bar`（现有 `parse_futu_bars` 可复用）

**Futu API 对应说明**：

| NT 请求 | Futu API | Futu Proto ID | 返回内容 |
|---------|----------|---------------|----------|
| request_bars | Qot_RequestHistoryKL | 3103 | klList: [{time, open, high, low, close, volume, turnover, ...}] |
| request_instrument | Qot_GetStaticInfo | 3202 | staticInfoList: [{security, name, lotSize, secType, listTime, ...}] |
| request_quote_ticks | Qot_GetBasicQot | 3004 | basicQotList: [{security, curPrice, openPrice, highPrice, lowPrice, volume, ...}] |
| request_trade_ticks | Qot_GetTicker | 3010 | tickerList: [{time, sequence, dir, price, volume, turnover, ...}]（最多1000条） |
| request_order_book | Qot_GetOrderBook | 3012 | orderBookAskList, orderBookBidList: [{price, volume, orderCount}] |

---

## 五、ExecClient 方法 (`execution.py`)

### 已实现 ✅

| NT 方法 | Futu API | Proto ID | 说明 |
|---------|----------|----------|------|
| `_connect()` | InitConnect + GetAccList + UnlockTrade | 1001,2001,2005 | 完整 |
| `_disconnect()` | - | - | 完整 |
| `_submit_order()` | Trd_PlaceOrder | 2202 | 支持 LIMIT/MARKET，传 sec_market |
| `_modify_order()` | Trd_ModifyOrder | 2205 | ModifyOrderOp=1 (Normal) |
| `_cancel_order()` | Trd_ModifyOrder | 2205 | ModifyOrderOp=2 (Cancel) |

### 需要实现 ❌

| # | NT 方法 | Futu API | Proto ID | 依赖 | 说明 |
|---|---------|----------|----------|------|------|
| E-1 | `generate_order_status_report()` | Trd_GetOrderList | 2201 | P0-1 | 查询指定订单状态 → `OrderStatusReport` |
| E-1b | `generate_order_status_reports()` | Trd_GetOrderList | 2201 | P0-1 | **批量**查询所有订单 → `list[OrderStatusReport]`（NT reconciliation 调用） |
| E-2 | `generate_fill_reports()` | Trd_GetOrderFillList | 2211 | P0-2 | 查询成交列表 → `FillReport[]` |
| E-3 | `generate_position_status_reports()` | Trd_GetPositionList | 2102 | P0-3 | 查询持仓 → `PositionStatusReport[]` |
| E-4 | `_generate_account_state()` | Trd_GetFunds | 2101 | P0-4 | 查询资金 → `AccountState` 事件 |
| E-5 | 订单事件生成 | Trd_UpdateOrder push | 2208 | P1-5 | 推送 → `OrderAccepted`/`OrderFilled`/`OrderCanceled`/`OrderRejected` |
| E-6 | 成交事件生成 | Trd_UpdateOrderFill push | 2218 | P1-6 | 推送 → `OrderFilled` (与 E-5 配合) |
| E-7 | `_cancel_all_orders()` | Trd_GetOrderList + Trd_ModifyOrder | 2201+2205 | P0-1 | 查询所有活跃订单 → 逐个撤单 |

**E-1 实现细节** — `generate_order_status_report(instrument_id, client_order_id, venue_order_id)`:
```python
# 1. 调用 get_order_list(trd_env, acc_id, trd_market, filter=None)
# 2. 遍历结果找 matching order_id
# 3. 构造 OrderStatusReport:
#    - account_id, instrument_id, client_order_id, venue_order_id
#    - order_side: futu_trd_side_to_nautilus(order.trdSide)
#    - order_type: futu_order_type_to_nautilus(order.orderType)
#    - order_status: futu_order_status_to_nautilus(order.orderStatus)  # 需新增
#    - quantity, filled_qty, price, avg_px, ts_accepted, ts_last
```

**E-2 实现细节** — `generate_fill_reports(instrument_id, venue_order_id, start, end)`:
```python
# 1. 调用 get_order_fill_list(trd_env, acc_id, trd_market, filter=None)
# 2. 过滤匹配的 fills
# 3. 构造 FillReport:
#    - account_id, instrument_id, venue_order_id
#    - trade_id: TradeId(str(fill.fillID))
#    - order_side, last_qty, last_px
#    - ts_event: 从 fill.createTime 解析
```

**E-3 实现细节** — `generate_position_status_reports(instrument_id, start, end)`:
```python
# 1. 调用 get_position_list(trd_env, acc_id, trd_market, filter=None)
# 2. 构造 PositionStatusReport:
#    - account_id, instrument_id
#    - position_side: LONG/SHORT/FLAT
#    - quantity: position.qty
#    - avg_px_open: position.costPrice
#    - unrealized_pnl: position.plVal
```

**需新增的解析函数** (`parsing/orders.py`):
- `futu_order_status_to_nautilus(status: int) -> OrderStatus` — Futu 10 种状态 → NT OrderStatus
- `parse_futu_order_to_report(order: dict) -> OrderStatusReport`
- `parse_futu_fill_to_report(fill: dict) -> FillReport`
- `parse_futu_position_to_report(position: dict) -> PositionStatusReport`

---

## 六、InstrumentProvider (`providers.py`)

| # | NT 方法 | 状态 | 说明 |
|---|---------|------|------|
| - | `load_async()` | ⚠️ | 只解析 Equity，不支持其他类型 |
| - | `load_ids_async()` | ✅ | 逐个调用 load_async |
| I-1 | `load_all_async()` | ❌ | Futu 无"全量"接口。可按配置的 market + plate_code 批量加载 |
| I-2 | 多类型解析 | ❌ | 需支持 Future/Option/Warrant |

### I-2 多类型解析细节

Futu `Qot_GetStaticInfo` 返回 `secType` 字段：

| secType | 含义 | NT 类型 |
|---------|------|---------|
| 1 | BOND | 🚫 NT 不直接支持 |
| 2 | IDX (指数) | 🚫 NT 不直接支持 |
| 3 | STOCK | `Equity` ✅ 已实现 |
| 4 | ETF | `Equity` (可复用) |
| 5 | WARRANT (窝轮) | `Equity` (简化处理) 或 🚫 |
| 6 | CBBC (牛熊证) | `Equity` (简化处理) 或 🚫 |
| 7 | OPTION | `OptionsContract` |
| 8 | FUTURE | `FuturesContract` |

**关键字段** (Futu staticInfo)：
- `secType`: 证券类型
- `lotSize`: 每手股数
- `listTime`: 上市日期
- `expiryDate`: 到期日 (期权/期货/窝轮)
- `strikePrice`: 行权价 (期权)
- `optionType`: CALL/PUT (期权)
- `stockOwner`: 正股代码 (窝轮/牛熊证)
- `priceSpread`: 最小价差

---

## 七、Rust 侧新增功能

### 需新增的 Rust 函数

| # | 模块 | 函数 | Proto ID | protobuf 生成状态 | 说明 |
|---|------|------|----------|-------------------|------|
| R-1 | `quote/` | `get_order_book()` | 3012 | ✅ `qot_get_order_book` | 请求盘口快照 |
| R-2 | `quote/` | `get_ticker()` | 3010 | ✅ `qot_get_ticker` | 请求最近逐笔列表（最多1000条） |
| R-3 | `trade/` | `sub_acc_push()` | 2008 | 需检查 | 订阅账户交易推送 |
| R-4 | `trade/` | `get_history_order_list()` | 2221 | 需生成 proto | 历史订单查询 |
| R-5 | `trade/` | `get_history_order_fill_list()` | 2222 | 需生成 proto | 历史成交查询 |
| R-6 | `trade/` | `get_max_trd_qtys()` | 2111 | 需生成 proto | 最大可买/卖数量 |
| R-7 | `quote/` | `get_global_state()` | 1002 | 需新增 proto + 函数 | 连接健康检查 + 市场状态 |
| R-8 | `quote/` | `get_option_chain()` | 3209 | 需新增 proto + 函数 | 期权链发现（calls/puts/strikes） |
| R-9 | `quote/` | `get_future_info()` | 3218 | 需新增 proto + 函数 | 期货合约规格（合约乘数/最小变动/交易时间） |
| R-10 | `quote/` | `get_market_state()` | 3223 | 需新增 proto + 函数 | 单证券市场状态（盘前/盘中/午休/收盘） |
| R-11 | `trade/` | `get_margin_ratio()` | 2223 | 需新增 proto + 函数 | 保证金比率（初始/维持/追缴） |

### 已有但需检查的 Rust 功能

| 功能 | 文件 | 状态 |
|------|------|------|
| `reg_push()` | `quote/subscribe.rs` | ✅ 已实现，Python 未暴露 |
| `subscribe_push()` | `client/mod.rs` | ✅ 已实现，Python 未暴露 |
| Dispatcher push 分发 | `client/dispatcher.rs` | ✅ 已实现 |
| recv loop 自动分发 | `client/mod.rs` | ✅ 已实现 |

---

## 八、解析层新增 (`nautilus_futu/parsing/`)

### market_data.py 需新增

| # | 函数 | 输入 | 输出 | 用途 |
|---|------|------|------|------|
| MD-1 | `parse_futu_order_book()` | `{orderBookAskList, orderBookBidList}` | `list[OrderBookDelta]` | 盘口解析 |
| MD-2 | `parse_futu_update_quote()` | push 3005 数据 | `QuoteTick` | 实时报价推送 |
| MD-3 | `parse_futu_update_ticker()` | push 3011 数据 | `list[TradeTick]` | 逐笔推送 |
| MD-4 | `parse_futu_update_kl()` | push 3007 数据 | `Bar` | K线推送 |

### orders.py 需新增

| # | 函数 | 输入 | 输出 | 用途 |
|---|------|------|------|------|
| OD-1 | `futu_order_status_to_nautilus()` | `int (0-11)` | `OrderStatus` | 订单状态映射 |
| OD-2 | `futu_time_in_force_to_nautilus()` | `int (0-1)` | `TimeInForce` | TIF 映射 |
| OD-3 | `parse_futu_order_to_report()` | `dict` | `OrderStatusReport` | 订单报告 |
| OD-4 | `parse_futu_fill_to_report()` | `dict` | `FillReport` | 成交报告 |
| OD-5 | `parse_futu_position_to_report()` | `dict` | `PositionStatusReport` | 持仓报告 |
| OD-6 | `parse_futu_order_update()` | push 2208 数据 | NT 订单事件 | 订单推送解析 |
| OD-7 | `parse_futu_fill_update()` | push 2218 数据 | NT 成交事件 | 成交推送解析 |

---

## 九、基础设施改进

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| IF-1 | 连接共享 | P2 | Data/Exec Client 共享同一 TCP 连接（Futu OpenD 限制并发连接数）。Factory 需改为共享 `PyFutuClient` 实例 |
| IF-2 | 断线重连 | P2 | Rust `FutuConfig` 已有 `reconnect` + `reconnect_interval_secs` 字段，但未实装重连逻辑 |
| IF-3 | RSA 加密 | P3 | `FutuConfig.rsa_key_path` 已预留但未实装。需读取 RSA 私钥 → InitConnect 时加密 connAESKey |
| IF-4 | rehab_type 可配置 | P3 | `data.py._request_bars` 中 `rehab_type` 硬编码为 1（前复权），应加入 `FutuDataClientConfig` |

---

## 十、额外高优先级 API（文档分析补充）

以下 API 从 Futu 完整文档分析中识别，对完整适配器至关重要：

### 期权/期货工具发现（InstrumentProvider 扩展）

| Futu API | Proto ID | 说明 | NT 用途 |
|----------|----------|------|---------|
| GetOptionChain | 3209 | 期权链：calls/puts、行权价、到期日 | `OptionsContract` 工具创建 |
| GetOptionExpirationDate | 3224 | 期权到期日枚举（GetOptionChain 前置） | 期权工具发现流程 |
| GetFutureInfo | 3218 | 期货合约规格：乘数、最小变动、报价货币、交易时间 | `FuturesContract` 工具创建 |
| GetRehab | 3105 | 复权因子（前复权/后复权公式系数） | 历史数据准确性 |

### 连接与市场状态

| Futu API | Proto ID | 说明 | NT 用途 |
|----------|----------|------|---------|
| GetGlobalState | 1002 | 连接健康：市场状态、登录状态、服务器时间 | 连接初始化 + 健康检查 |
| GetMarketState | 3223 | 单证券市场状态（盘前/开盘/午休/收盘） | 订单路由 + session 管理 |
| RequestHistoryKLQuota | 3104 | 历史K线 API 配额（30天滚动窗口） | 请求频率控制 |

### 风控与账户

| Futu API | Proto ID | 说明 | NT 用途 |
|----------|----------|------|---------|
| Trd_GetMarginRatio | 2223 | 保证金比率：初始(IM)/维持(MM)/追缴(MCM)/警戒 | `RiskEngine` + `AccountState` |
| Trd_GetAccCashFlow | 2226 | 资金流水：入金/出金/分红/手续费/交割 | 账户余额对账 + PnL 追踪 |
| Qot_GetSubInfo | 3003 | 订阅配额监控（已用/剩余） | 订阅管理 |

### 交易日历

| Futu API | Proto ID | 说明 | NT 用途 |
|----------|----------|------|---------|
| RequestTradingDays | 3219 | 交易日历（含节假日） | Bar 聚合 + session 调度 |

---

## 十一、Futu API 可用但无对应 NT 接口（低优先级）

这些 Futu API 暂无直接的 NautilusTrader 标准接口对应，但可作为扩展：

| Futu API | Proto ID | 说明 | 可能用途 |
|----------|----------|------|----------|
| Qot_UpdateRT | 3009 | 分时数据推送 | 自定义数据类型 / VWAP |
| Qot_GetPlateSet | 3204 | 获取板块列表 | load_all_async 过滤 |
| Qot_GetPlateSecurity | 3205 | 获取板块成分股 | load_all_async 实现 |
| Qot_GetReference | 3206 | 关联窝轮/期货发现 | 衍生品工具查找 |
| Qot_GetWarrant | 3210 | 窝轮筛选（HK市场） | 窝轮交易支持 |
| Qot_GetUserSecurity | 3213 | 用户自选股列表 | 监控列表驱动订阅 |
| Qot_GetStockFilter | 3215 | 股票筛选器 | 策略选股 |
| Qot_GetIPOList | 3217 | IPO 信息 | 信息展示 |
| Trd_GetMaxTrdQtys | 2111 | 最大可买/卖数量 | 下单前风控 |
| Trd_GetHistoryOrderList | 2221 | 历史订单查询 | generate_order_status_report 扩展 |
| Trd_GetHistoryOrderFillList | 2222 | 历史成交查询 | generate_fill_reports 扩展 |
| Qot_GetCapitalFlow | 3211 | 资金流向 | 策略信号 |
| Qot_GetCapitalDistribution | 3212 | 资金分布 | 策略信号 |
| Qot_SetPriceReminder | 3220 | 价格提醒设置 | 自定义告警 |
| Qot_UpdateBroker | 3015 | 经纪商队列推送（HK） | L2 数据增强 |

---

## 十二、推荐实施顺序

### 阶段 1：PyO3 绑定 + 报告查询（P0）
**目标**：补全 PyO3 层，使 ExecClient 报告方法可用，消除 reconciliation 警告

1. `P0-1` ~ `P0-5`: 添加 5 个查询方法到 PyFutuClient
2. `E-1` + `E-1b`: 实现 generate_order_status_report (单个) + generate_order_status_reports (批量)
3. `E-2` ~ `E-3`: 实现 generate_fill_reports + generate_position_status_reports
4. `E-4`: 实现 generate_account_state
5. `E-7`: 实现 cancel_all_orders（查询活跃订单 → 逐个撤单）
6. `OD-1` ~ `OD-5`: 添加所有解析函数
7. 测试：单元测试 + mock 测试

### 阶段 2：推送链路（P1）
**目标**：打通实时推送，使订阅真正生效

1. `P0-6`: PyO3 层暴露推送轮询接口
2. `R-3`: Rust 侧添加 sub_acc_push
3. `P1-1` ~ `P1-4`: DataClient 行情推送处理
4. `P1-5` ~ `P1-6`: ExecClient 交易推送处理
5. `MD-1` ~ `MD-4`, `OD-6` ~ `OD-7`: 推送解析函数
6. 测试：mock push 数据测试

### 阶段 3：DataClient 补全 + 工具扩展（P2）
**目标**：所有 DataClient 方法完整可用，支持期货/期权工具

1. `D-1` ~ `D-2`: 取消订阅 order_book / bars
2. `D-3` ~ `D-5`: request_instrument / quote_ticks / trade_ticks
3. `P0-7`, `R-1`, `R-2`: 盘口请求 + 逐笔请求（Rust 新增）
4. `I-2`: 多类型工具解析（Equity/ETF/Future/Option）
5. `R-8` ~ `R-9`: 期权链 + 期货合约规格（Rust 新增）
6. `R-10`: 市场状态查询（盘前/盘中/休市）

### 阶段 4：基础设施 + 风控（P3）
**目标**：生产环境可靠性 + 风控支持

1. `IF-1`: 连接共享
2. `IF-2`: 断线重连
3. `IF-3`: RSA 加密
4. `IF-4`: rehab_type 可配置
5. `R-7`: GetGlobalState 连接健康检查
6. `R-11`: 保证金比率查询 → RiskEngine 集成

---

## 十三、Futu API 枚举速查

### OrderType (订单类型)
| 值 | 名称 | NT 映射 |
|----|------|---------|
| 1 | Normal (限价) | OrderType.LIMIT ✅ |
| 2 | Market (市价) | OrderType.MARKET ✅ |
| 5 | AbsoluteLimit (绝对限价) | OrderType.LIMIT |
| 6 | Auction (竞价) | 🚫 NT 无直接对应 |
| 10 | SpecialLimit_All (特别限价,全量) | OrderType.LIMIT |
| 11 | SpecialLimit (特别限价) | OrderType.LIMIT |
| 12 | Enhanced_Limit (增强限价) | OrderType.LIMIT |
| 13 | At_Auction (竞价市价) | OrderType.MARKET |
| 14 | At_Auction_Limit (竞价限价) | OrderType.LIMIT |
| 15 | Odd_Lot (碎股) | OrderType.LIMIT |

### OrderStatus (订单状态)
| 值 | 名称 | NT OrderStatus |
|----|------|----------------|
| 0 | Unsubmitted | INITIALIZED |
| 1 | Unknown | INITIALIZED |
| 2 | WaitingSubmit | SUBMITTED |
| 3 | Submitting | SUBMITTED |
| 5 | SubmitFailed | REJECTED |
| 10 | Submitted (已提交/等待成交) | ACCEPTED |
| 11 | FilledPart | PARTIALLY_FILLED |
| 12 | FilledAll | FILLED |
| 13 | CancellingPart | PENDING_CANCEL |
| 14 | CancellingAll | PENDING_CANCEL |
| 15 | CancelledPart | CANCELED |
| 16 | CancelledAll | CANCELED |
| 17 | Failed | REJECTED |
| 18 | Disabled | CANCELED |
| 19 | Deleted | CANCELED |
| 20 | FillCancelled | CANCELED |

### TrdSide (交易方向)
| 值 | 名称 | NT 映射 |
|----|------|---------|
| 1 | Buy | OrderSide.BUY ✅ |
| 2 | Sell | OrderSide.SELL ✅ |
| 3 | SellShort | OrderSide.SELL ✅ |
| 4 | BuyBack | OrderSide.BUY ✅ |

### TimeInForce (有效期)
| 值 | 名称 | NT 映射 |
|----|------|---------|
| 0 | DAY | TimeInForce.DAY |
| 1 | GTC | TimeInForce.GTC |

### TrdEnv (交易环境)
| 值 | 名称 |
|----|------|
| 0 | Simulate (模拟) |
| 1 | Real (真实) |

### TrdMarket (交易市场)
| 值 | 名称 |
|----|------|
| 1 | HK (香港) |
| 2 | US (美国) |
| 3 | CN (A股) |
| 4 | HKCC (A股通) |
| 5 | Futures (期货) |

### QotMarket (行情市场)
| 值 | 名称 | Venue |
|----|------|-------|
| 1 | HK_Security | HKEX |
| 2 | HK_Future | HKEX |
| 11 | US_Security | NYSE/NASDAQ |
| 21 | CNSH_Security | SSE |
| 22 | CNSZ_Security | SZSE |
| 31 | SG_Security | SGX |
| 32 | SG_Future | SGX |
| 41 | JP_Security | (需新增) |

### ModifyOrderOp (改单操作)
| 值 | 名称 | 用途 |
|----|------|------|
| 1 | Normal | 改价/改量 |
| 2 | Cancel | 撤单 ✅ |
| 3 | Disable | 使失效（盘前生效） |
| 4 | Enable | 使生效（盘前生效） |
| 5 | Delete | 删除（已撤/已失效订单） |

---

## 十四、缺失的 Futu API（NT 需要但 Futu 不提供）

| NT 功能 | 说明 | 替代方案 |
|---------|------|----------|
| `request_trade_ticks` 精确历史 | Futu 的 GetTicker 只返回最近 ~1000 条，无日期范围查询 | 近实时可用，长历史不可用 |
| RFQ (Request for Quote) | NT dYdX 适配器有此功能 | 🚫 Futu 不支持 |
| 挂单簿 L3 | NT 支持 FULL_DEPTH | Futu 只有 L2 (10档) |
| `cancel_all_orders` 批量撤单 | 部分 NT 适配器支持 | 需逐个调用 modify_order(op=Cancel) |
| 条件单管理 | Futu 有条件单但 NT 无标准接口 | 可作为扩展 |
