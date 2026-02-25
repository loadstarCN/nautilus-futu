# nautilus-futu

Futu OpenD adapter for [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) — 通过富途 OpenD 网关接入港股、美股、A股等市场的量化交易适配器。

## 特性

- **独立安装包** — 不依赖 NautilusTrader 主仓库，自主控制版本发布
- **Rust 协议层** — 用 Rust 实现 Futu OpenD TCP 二进制协议，高性能低延迟
- **无 protobuf 冲突** — 不依赖 `futu-api` Python 包，Rust 侧用 prost 处理 protobuf，彻底避免版本冲突
- **完整功能覆盖** — 行情订阅、历史K线、下单/改单/撤单、账户资金/持仓查询

## 支持市场

| 市场 | 行情 | 交易 |
|------|------|------|
| 港股 (HK) | ✅ | ✅ |
| 美股 (US) | ✅ | ✅ |
| A股 (CN) | ✅ | ✅ |

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

```python
import asyncio
from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig

async def main():
    # 导入 Rust 客户端
    from nautilus_futu._rust import PyFutuClient

    client = PyFutuClient()
    client.connect("127.0.0.1", 11111, "nautilus", 100)

    # 获取行情快照
    quotes = client.get_basic_qot([(1, "00700")])  # 腾讯控股
    for q in quotes:
        print(f"{q['code']}: {q['cur_price']}")

    # 获取历史K线
    bars = client.get_history_kl(
        market=1,
        code="00700",
        rehab_type=1,      # 前复权
        kl_type=2,          # 日K
        begin_time="2025-01-01",
        end_time="2025-12-31",
    )
    print(f"获取到 {len(bars)} 根K线")

    client.disconnect()

asyncio.run(main())
```

### 集成 NautilusTrader

```python
from nautilus_trader.live.node import TradingNode
from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig
from nautilus_futu.factories import FutuLiveDataClientFactory, FutuLiveExecClientFactory

node = TradingNode()

# 注册 Futu 适配器
node.add_data_client_factory("FUTU", FutuLiveDataClientFactory)
node.add_exec_client_factory("FUTU", FutuLiveExecClientFactory)

# 配置
data_config = FutuDataClientConfig(
    host="127.0.0.1",
    port=11111,
)
exec_config = FutuExecClientConfig(
    host="127.0.0.1",
    port=11111,
    trd_env=0,          # 0=模拟, 1=真实
    trd_market=1,       # 1=港股, 2=美股
    unlock_pwd_md5="",  # 真实交易需要填写
)

node.build()
node.run()
```

## 项目结构

```
nautilus-futu/
├── crates/futu/           # Rust 核心
│   ├── proto/             # Futu OpenD .proto 文件
│   └── src/
│       ├── protocol/      # TCP 协议：包头、编解码、加解密
│       ├── client/        # 连接管理、握手、心跳、消息分发
│       ├── quote/         # 行情：订阅、快照、历史K线
│       ├── trade/         # 交易：账户、下单、查询
│       ├── generated/     # Protobuf 生成的 Rust 类型
│       └── python/        # PyO3 绑定
├── nautilus_futu/          # Python NautilusTrader 适配器
│   ├── data.py            # FutuLiveDataClient
│   ├── execution.py       # FutuLiveExecutionClient
│   ├── providers.py       # FutuInstrumentProvider
│   └── parsing/           # 数据类型转换
├── tests/
└── examples/
```

## 开发

```bash
# 安装 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

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

# 运行 Rust 测试
cargo test

# 运行 Python 测试
pytest tests/python -v
```

## 架构

```
Python 应用 / NautilusTrader
        │
        ▼
nautilus_futu (Python 适配器层)
        │
        ▼ PyO3
nautilus_futu._rust (Rust 编译的扩展模块)
        │
        ▼ TCP + Protobuf + AES
Futu OpenD 网关
        │
        ▼
港股 / 美股 / A股 交易所
```

## 许可证

MIT

## 相关链接

- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
- [Futu OpenD 文档](https://openapi.futunn.com/futu-api-doc/)
- [Futu API Proto 定义](https://github.com/FutunnOpen/py-futu-api)
