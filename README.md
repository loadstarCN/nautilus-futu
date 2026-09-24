# nautilus-futu

Futu OpenD adapter for [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) — 通过富途 OpenD 网关接入港股、美股、沪深港通等市场的量化交易适配器。

## 特性

- **独立安装包** — 不依赖 NautilusTrader 主仓库，自主控制版本发布
- **Rust 协议层** — 用 Rust 实现 Futu OpenD TCP 二进制协议（含 RSA/AES 加密），高性能低延迟
- **无 protobuf 冲突** — 不依赖 `futu-api` Python 包，Rust 侧用 prost 处理 protobuf
- **完整交易生命周期** — 下单 / 改单 / 撤单 / 条件单 / 订单列表，订单与成交推送映射为 Nautilus 事件，支持对账（含历史订单/成交回溯）
- **行情** — 真实买卖一档报价（来自盘口）、逐笔成交、L2 盘口（增量或 `OrderBookDepth10` 十档快照）、K 线推送（完成 K 线 / 可选修订）、分页历史 K 线
- **市场状态** — 午休、收市竞价、盘前盘后等市场状态映射为 `InstrumentStatus` 事件
- **连接管理** — 行情与交易共用一条 TCP 连接，断线检测、自动重连并恢复订阅，请求超时保护

## 支持市场

| 市场 | 行情 | 交易 | 备注 |
|------|------|------|------|
| 港股 (HKEX) | ✅ | ✅ | 正股 / ETF / 窝轮 / 牛熊 / 期权 |
| 美股 (NYSE / NASDAQ) | ✅ | ✅ | 支持盘前盘后成交 |
| 沪深 (SSE / SZSE) | ✅ | ✅ | 交易需开通沪深港通（TrdMarket_HKCC），结算币种 CNH |
| 新加坡 (SGX) | ✅ | — | 期货行情 |

## 前置条件

- Python >= 3.12
- [Futu OpenD](https://openapi.futunn.com/futu-api-doc/opend/opend-cmd.html) 网关运行中（默认 `127.0.0.1:11111`）
- Rust 工具链（从源码安装时需要）

## 安装

```bash
pip install nautilus-futu
```

从源码安装：

```bash
git clone https://github.com/loadstarCN/nautilus-futu.git
cd nautilus-futu
pip install .
```

## 快速上手

### 集成 NautilusTrader

```python
from nautilus_trader.config import InstrumentProviderConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig
from nautilus_futu.factories import FutuLiveDataClientFactory, FutuLiveExecClientFactory

config = TradingNodeConfig(
    data_clients={
        "FUTU": FutuDataClientConfig(
            host="127.0.0.1",
            port=11111,
            instrument_provider=InstrumentProviderConfig(load_ids=frozenset({"00700.HKEX", "AAPL.NYSE"})),
        ),
    },
    exec_clients={
        "FUTU": FutuExecClientConfig(
            host="127.0.0.1",
            port=11111,          # 与 data client 相同 → 共用一条 TCP 连接
            trd_env=0,           # 0=模拟, 1=真实
            trd_market=1,        # 默认交易市场：1=港股, 2=美股, 4=沪深港通
            account_type="CASH", # 或 "MARGIN"
            unlock_pwd_md5="",   # 真实交易需要填写
        ),
    },
)

node = TradingNode(config=config)
node.add_data_client_factory("FUTU", FutuLiveDataClientFactory)
node.add_exec_client_factory("FUTU", FutuLiveExecClientFactory)
node.build()
node.run()
```

品种 ID 使用交易所作为 venue（`00700.HKEX`、`AAPL.NYSE`、`600519.SSE`），
适配器默认把这些 venue 路由到 FUTU 客户端，并把 FUTU 账户注册为所有 venue 的账户，
无需额外配置 `routing`。

### 策略中可用的操作

```python
self.subscribe_quote_ticks(instrument_id)        # 买卖一档（来自盘口推送）
self.subscribe_trade_ticks(instrument_id)        # 逐笔成交
self.subscribe_order_book_deltas(instrument_id)  # L2 盘口（最多 10 档）
self.subscribe_order_book_depth(instrument_id)   # OrderBookDepth10 十档快照（与盘口共用一个订阅）
self.subscribe_instrument_status(instrument_id)  # 市场状态：开盘 / 午休 / 收市竞价 / 收盘 ...
self.subscribe_bars(BarType.from_str("00700.HKEX-1-MINUTE-LAST-EXTERNAL"))
self.request_bars(bar_type, start=..., end=...)  # 历史 K 线（自动分页）

self.submit_order(self.order_factory.limit(...))            # 限价
self.submit_order(self.order_factory.market(...))           # 市价
self.submit_order(self.order_factory.stop_limit(...))       # 止损限价
self.submit_order(self.order_factory.trailing_stop_market(...))  # 跟踪止损
self.submit_order_list(order_list)                          # 逐腿下单（OCO/OUO 需策略开启 manage_contingent_orders）
self.modify_order(order, price=...)
self.cancel_all_orders(instrument_id)
```

支持的订单类型：`LIMIT`、`MARKET`、`STOP_MARKET`、`STOP_LIMIT`、`MARKET_IF_TOUCHED`、
`LIMIT_IF_TOUCHED`、`TRAILING_STOP_MARKET`、`TRAILING_STOP_LIMIT`；有效期 `DAY` / `GTC`。
美股盘前盘后成交通过 `FutuExecClientConfig.fill_outside_rth` 或订单 tag `FUTU_RTH:1` 开启。

富途没有原生的括号单 / OTO 条件单，直接提交的 bracket 订单列表会被拒绝（以免止损单在开仓单成交前生效）。
请给子订单设置 `emulation_trigger`（如 `TriggerType.BID_ASK`），由 NautilusTrader 的 OrderEmulator 在母单成交后再释放子订单。
OCO/OUO 订单列表会先校验全部订单腿并统一标记为 SUBMITTED，再逐腿下单：某一腿被拒或在下单前被撤销时，
与它关联、尚未下单的腿直接撤销（不关联的腿照常下单）；尚未下单的腿收到改单时直接按新数量 / 价格下单。
单笔订单同样适用：下单请求进行中收到的撤单 / 改单会在拿到富途订单号后执行，`cancel_all_orders` 也会撤销在途订单。
下单请求超时等"结果未知"的失败不会被当作拒单：订单保持 SUBMITTED，待富途推送或在途订单检查确认。

`subscribe_instrument_status` 的 `InstrumentStatus.action` 映射：连续交易 → `TRADING`，午休 / 期货休市 → `PAUSE`，
开盘前竞价 / 美股盘前 → `PRE_OPEN`，港股收市竞价 (CAS) → `PRE_CLOSE`，美股盘后 / 夜盘 → `POST_CLOSE`，收盘 → `CLOSE`
（期权到期前的每日收盘报 `POST_CLOSE`，因为 NautilusTrader 会把期权链合约收到的 `CLOSE` 当作到期并移出期权链）；
富途原始状态名（如 `REST`、`HK_CAS`）放在 `trading_event` 中。港股期货和恒指 / 国指等指数期权使用期货市场状态
（日盘 / 夜盘），港股股票期权使用股票市场状态。

### 直接使用 Rust 客户端

```python
from nautilus_futu._rust import PyFutuClient

client = PyFutuClient()
client.connect("127.0.0.1", 11111, "nautilus", 100)

quotes = client.get_security_snapshot([(1, "00700")])   # 含 bid/ask
bars = client.get_history_kl(1, "00700", rehab_type=1, kl_type=2,
                             begin_time="2025-01-01", end_time="2025-12-31")  # 自动分页

channel = client.start_push([3013])                       # 盘口推送
client.subscribe([(1, "00700")], [2], True)
msg = client.poll_push(channel, 1000)                     # 断线时抛 ConnectionError

# 历史订单 / 成交（时间为市场当地时间；两端都省略时为最近 90 天，只给一端时向另一端推 90 天）
fills = client.get_history_order_fill_list(1, acc_id, 1, begin_time="2026-09-01 00:00:00",
                                           end_time="2026-09-24 23:59:59", code_list=["00700"])
client.disconnect()
```

## 配置说明

| 配置项 | 说明 |
|--------|------|
| `rsa_key_path` | 与 OpenD 共用的 RSA 私钥（PEM），设置后握手 RSA 加密、后续 AES 加密 |
| `request_timeout` | 单个请求等待 OpenD 应答的秒数，默认 15 |
| `reconnect` / `reconnect_interval` | 断线自动重连及间隔 |
| `handle_revised_bars` | 为 True 时把未完成 K 线的每次更新以 `is_revision=True` 推送 |
| `order_book_depth` | 盘口档位上限（港股/美股 10，A 股 5） |
| `market_status_interval` | 市场状态轮询间隔秒数，默认 10（仅在订阅了 instrument status 时轮询） |
| `account_type` | `CASH` 或 `MARGIN`，需与富途账户类型一致 |
| `set_specific_venue` | 把 FUTU 账户注册为所有 venue 的账户（同节点跑其它适配器时关闭） |
| `account_refresh_interval` | 定时刷新资金秒数（0 关闭；订单/成交推送后总会刷新） |

品种加载：`InstrumentProviderConfig(load_all=True, filters={...})` 支持
`{"venues": ["HKEX"]}`、`{"markets": [1, 11]}`、`{"plates": [(1, "HK.BK1001")]}`、
`{"option_chains": [{"instrument_id": "00700.HKEX", "begin": "2026-10-01", "end": "2026-12-31"}]}`。

## 注意事项

- 港股 tick 随价格档位变化，品种精度固定为 0.001；下单前可用 `nautilus_futu.parsing.instruments.hk_tick_size(price)` 取当前档位 tick。
- Futu 的人民币币种为 `CNH`，沪深品种与资金均使用 `CNH`。
- 历史 K 线受富途 30 天额度限制，`request_bars` 无 `limit` 时按时间范围全部拉取。
- 成交手续费不在成交推送中，`OrderFilled.commission` 为 0，可用 `PyFutuClient.get_order_fee` 查询。
- 对账回溯：`LiveExecEngineConfig(reconciliation_lookback_mins=...)` 早于当天时，会额外拉取历史订单 / 成交，
  使节点离线期间的成交也能对账；部分环境（如模拟盘）不提供历史成交时仅记录警告，当天数据照常对账。
- OpenD 不推送市场状态变化，`subscribe_instrument_status` 通过 `get_global_state` 轮询实现，状态变化最多延迟一个轮询间隔。

## 项目结构

```
nautilus-futu/
├── crates/futu/           # Rust 核心
│   ├── proto/             # Futu OpenD .proto 文件
│   └── src/
│       ├── protocol/      # TCP 协议：包头、编解码、RSA/AES
│       ├── client/        # 连接、握手、心跳、消息分发、超时
│       ├── quote/         # 行情：订阅、快照、历史K线（分页）
│       ├── trade/         # 交易：账户、下单、查询
│       ├── generated/     # Protobuf 生成的 Rust 类型
│       └── python/        # PyO3 绑定（含 poll_push_async）
├── nautilus_futu/         # Python NautilusTrader 适配器
│   ├── connection.py      # 共享连接管理（引用计数、重连代数）
│   ├── data.py            # FutuLiveDataClient
│   ├── execution.py       # FutuLiveExecutionClient
│   ├── providers.py       # FutuInstrumentProvider
│   ├── parsing/           # 数据类型转换
│   └── _rust.pyi          # Rust 扩展类型存根
├── tests/python/          # 单元测试 + 假 OpenD 端到端测试
└── examples/
```

## 开发

```bash
# 创建并激活虚拟环境
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

# 安装开发依赖
pip install -r requirements-dev.txt

# 开发模式构建（自动编译 Rust 并安装 Python 包）
maturin develop

# Rust 测试 / lint
cargo test
cargo clippy --all-targets -- -D warnings

# Python 测试 / lint
pytest tests/python -v
ruff check nautilus_futu tests

# 从 proto 重新生成 Rust 类型（需要 protoc）
cargo build --features regenerate-protos
```
