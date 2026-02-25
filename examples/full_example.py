#!/usr/bin/env python3
"""
nautilus-futu 完整功能示例
========================

本文件演示 nautilus-futu 适配器的所有功能，包括：

  1. 底层 Rust 客户端 (PyFutuClient) 直接调用
     - 连接/断开
     - 行情订阅与推送
     - 静态信息、快照、报价、逐笔、盘口、K线
     - 交易账户、下单、改单、撤单、查询
     - 全局状态查询 (GetGlobalState)

  2. NautilusTrader 集成 (TradingNode)
     - 通过 FutuDataClientConfig / FutuExecClientConfig 配置
     - 通过工厂类注册并自动连接
     - Data + Exec 共享同一 TCP 连接
     - 行情订阅 & 历史数据请求
     - 下单/撤单策略示例

前提条件:
  - Futu OpenD 网关已启动 (默认 127.0.0.1:11111)
  - 已构建 Rust 扩展: maturin develop --release
  - 已安装 nautilus_trader >= 1.221

运行:
  python examples/full_example.py
"""

from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal


# ============================================================================
#  第一部分: 底层 PyFutuClient 直接调用
# ============================================================================
# PyFutuClient 是 Rust 实现的客户端，通过 PyO3 暴露给 Python。
# 它直接与 Futu OpenD 进行 TCP/Protobuf 通信。
# 适合调试、脚本化操作或不需要 NautilusTrader 框架的场景。
# ============================================================================


def demo_rust_client():
    """演示 PyFutuClient 的所有底层 API。"""

    # ------------------------------------------------------------------
    # 1.1 创建客户端并连接
    # ------------------------------------------------------------------
    from nautilus_futu._rust import PyFutuClient

    client = PyFutuClient()

    # is_connected() 检查连接状态（用于连接共享时避免重复连接）
    print(f"连接前: is_connected = {client.is_connected()}")  # False

    # connect(host, port, client_id, client_ver)
    #   - host/port: Futu OpenD 网关地址
    #   - client_id: 客户端标识（自定义字符串）
    #   - client_ver: 客户端版本号
    client.connect("127.0.0.1", 11111, "nautilus_example", 100)
    print(f"连接后: is_connected = {client.is_connected()}")  # True

    # ------------------------------------------------------------------
    # 1.2 全局状态查询 (GetGlobalState, Proto 1002)
    # ------------------------------------------------------------------
    # 返回各市场交易状态、是否已登录行情/交易、服务器版本等信息
    # 用于健康检查和市场状态监控
    state = client.get_global_state()
    print("\n=== 全局状态 ===")
    print(f"  港股市场状态: {state.get('market_hk')}")
    #   市场状态值:
    #     0=None, 1=Auction(竞价), 2=WaitingOpen(待开盘),
    #     3=Morning(早盘), 4=Rest(午休), 5=Afternoon(午盘),
    #     6=Closed(已收盘), 8=PreMarketBegin(盘前开始),
    #     9=PreMarketEnd(盘前结束), 10=AfterHoursBegin(盘后开始),
    #     11=AfterHoursEnd(盘后结束)
    print(f"  美股市场状态: {state.get('market_us')}")
    print(f"  沪股市场状态: {state.get('market_sh')}")
    print(f"  深股市场状态: {state.get('market_sz')}")
    print(f"  港股期货状态: {state.get('market_hk_future')}")
    print(f"  美股期货状态: {state.get('market_us_future')}")
    print(f"  新加坡期货:   {state.get('market_sg_future')}")
    print(f"  日本期货:     {state.get('market_jp_future')}")
    print(f"  行情已登录:   {state.get('qot_logined')}")
    print(f"  交易已登录:   {state.get('trd_logined')}")
    print(f"  服务器版本:   {state.get('server_ver')}")
    print(f"  服务器Build:  {state.get('server_build_no')}")
    print(f"  服务器时间:   {state.get('time')}")

    # ------------------------------------------------------------------
    # 1.3 获取静态信息 (GetStaticInfo, Proto 3202)
    # ------------------------------------------------------------------
    # 查询证券的基本属性：名称、每手股数、证券类型、上市日期等
    # securities 参数为 (market, code) 元组列表
    #   market: 1=港股, 2=港股期货, 11=美股, 21=沪股, 22=深股, 31=新加坡
    print("\n=== 静态信息 ===")
    static_info = client.get_static_info([
        (1, "00700"),   # 腾讯 (港股)
        (11, "AAPL"),   # 苹果 (美股)
    ])
    for info in static_info:
        print(f"  {info['code']}: name={info['name']}, "
              f"lot_size={info['lot_size']}, sec_type={info['sec_type']}")
        # sec_type: 3=股票, 4=ETF, 5=窝轮, 6=牛熊证, 7=期权, 8=期货
        # 期权额外字段: option_type, strike_price, strike_time, option_owner_code
        # 期货额外字段: last_trade_time, is_main_contract

    # ------------------------------------------------------------------
    # 1.4 获取报价快照 (GetSecuritySnapshot, Proto 3203)
    # ------------------------------------------------------------------
    # 获取证券的实时快照数据：当前价、开高低收、成交量、买卖盘
    print("\n=== 报价快照 ===")
    snapshots = client.get_security_snapshot([(1, "00700")])
    for snap in snapshots:
        print(f"  {snap['code']}: cur={snap['cur_price']}, "
              f"open={snap['open_price']}, high={snap['high_price']}, "
              f"low={snap['low_price']}, volume={snap['volume']}")
        print(f"    ask={snap['ask_price']}x{snap['ask_vol']}, "
              f"bid={snap['bid_price']}x{snap['bid_vol']}")

    # ------------------------------------------------------------------
    # 1.5 获取实时报价 (GetBasicQot, Proto 3004)
    # ------------------------------------------------------------------
    # 获取已订阅证券的实时基本报价
    # 注意：需要先订阅 SubType=1 (Basic) 才能获取
    print("\n=== 实时报价 ===")
    # 先订阅
    client.subscribe(
        securities=[(1, "00700")],
        sub_types=[1],   # SubType: 1=Basic(报价), 2=OrderBook(盘口),
                         #          4=Ticker(逐笔), 5=RT(分时),
                         #          6=KL_Day, 7=KL_5Min, 8=KL_15Min,
                         #          9=KL_30Min, 10=KL_60Min, 11=KL_1Min
        is_sub=True,     # True=订阅, False=取消订阅
    )
    quotes = client.get_basic_qot([(1, "00700")])
    for q in quotes:
        print(f"  {q['code']}: price={q['cur_price']}, "
              f"open={q['open_price']}, volume={q['volume']}")

    # ------------------------------------------------------------------
    # 1.6 获取盘口 (GetOrderBook, Proto 3012)
    # ------------------------------------------------------------------
    # 获取买卖盘深度数据
    # 注意：需要先订阅 SubType=2 (OrderBook)
    print("\n=== 盘口 ===")
    client.subscribe([(1, "00700")], [2], True)
    order_book = client.get_order_book(
        market=1,
        code="00700",
        num=5,  # 档位数量，默认 10
    )
    print("  卖盘:")
    for ask in order_book.get("asks", [])[:3]:
        print(f"    价={ask['price']}, 量={ask['volume']}, "
              f"挂单数={ask['order_count']}")
    print("  买盘:")
    for bid in order_book.get("bids", [])[:3]:
        print(f"    价={bid['price']}, 量={bid['volume']}, "
              f"挂单数={bid['order_count']}")

    # ------------------------------------------------------------------
    # 1.7 获取逐笔成交 (GetTicker, Proto 3010)
    # ------------------------------------------------------------------
    # 获取最近的逐笔成交明细
    # 注意：需要先订阅 SubType=4 (Ticker)
    print("\n=== 逐笔成交 ===")
    client.subscribe([(1, "00700")], [4], True)
    tickers = client.get_ticker(
        market=1,
        code="00700",
        max_ret_num=5,  # 返回条数，默认 100
    )
    for t in tickers[:3]:
        dir_str = {1: "买入", 2: "卖出"}.get(t['dir'], "中性")
        print(f"  price={t['price']}, vol={t['volume']}, "
              f"方向={dir_str}, seq={t['sequence']}")

    # ------------------------------------------------------------------
    # 1.8 获取历史K线 (RequestHistoryKL, Proto 3103)
    # ------------------------------------------------------------------
    # 获取指定时间段的历史K线数据
    print("\n=== 历史K线 ===")
    klines = client.get_history_kl(
        market=1,
        code="00700",
        rehab_type=1,    # 复权类型: 0=不复权, 1=前复权, 2=后复权
        kl_type=2,       # K线类型: 1=1分钟, 2=日线, 3=周线, 4=月线,
                         #          6=5分钟, 7=15分钟, 8=30分钟, 9=60分钟
        begin_time="2024-01-01",   # 开始日期 "YYYY-MM-DD"
        end_time="2024-01-31",     # 结束日期 "YYYY-MM-DD"
        max_count=10,              # 最大返回条数（可选）
    )
    print(f"  获取 {len(klines)} 条K线")
    for kl in klines[:3]:
        print(f"  {kl['time']}: O={kl['open_price']}, H={kl['high_price']}, "
              f"L={kl['low_price']}, C={kl['close_price']}, V={kl['volume']}")

    # ------------------------------------------------------------------
    # 1.9 推送消息接收 (Push Loop)
    # ------------------------------------------------------------------
    # start_push 注册推送消息转发器，poll_push 轮询接收
    # start_push 支持追加模式：多次调用不会覆盖，而是追加新的 proto_id
    # 这是 DataClient + ExecClient 共享连接的基础
    print("\n=== 推送消息 ===")

    # 第一次调用：注册行情推送
    client.start_push([
        3005,  # BasicQot 推送（实时报价变更）
        3011,  # Ticker 推送（逐笔成交）
        3013,  # OrderBook 推送（盘口变更）
        3007,  # KL 推送（K线更新）
    ])

    # 第二次调用（追加模式）：注册交易推送
    # 不会覆盖第一次注册的行情推送
    client.start_push([
        2208,  # Order 推送（订单状态变更）
        2218,  # Fill 推送（成交通知）
    ])

    # poll_push 轮询接收推送消息
    # timeout_ms: 等待超时（毫秒），默认 100
    # 返回 dict {"proto_id": int, "data": ...} 或 None（超时）
    for _ in range(3):
        msg = client.poll_push(timeout_ms=200)
        if msg is not None:
            print(f"  收到推送: proto_id={msg['proto_id']}")
        else:
            print("  无推送消息（超时）")

    # ------------------------------------------------------------------
    # 1.10 交易功能
    # ------------------------------------------------------------------
    print("\n=== 交易功能 ===")

    # 获取账户列表 (TrdGetAccList, Proto 2001)
    accounts = client.get_acc_list()
    print(f"  账户数: {len(accounts)}")
    for acc in accounts:
        print(f"  acc_id={acc['acc_id']}, trd_env={acc['trd_env']}, "
              f"acc_type={acc['acc_type']}, "
              f"markets={acc['trd_market_auth_list']}")
        # trd_env: 0=模拟, 1=真实
        # acc_type: 1=现金账户, 2=保证金账户

    if not accounts:
        print("  无交易账户，跳过交易演示")
        client.disconnect()
        return

    # 选择模拟盘账户（trd_env=0），优先支持港股（trd_market=1）
    sim_acc = None
    for acc in accounts:
        markets = acc.get("trd_market_auth_list", [])
        if acc["trd_env"] == 0 and 1 in markets:
            sim_acc = acc
            break
    if not sim_acc:
        for acc in accounts:
            if acc["trd_env"] == 0:
                sim_acc = acc
                break
    if not sim_acc:
        print("  无模拟盘账户，跳过交易演示")
        client.disconnect()
        return

    acc_id = sim_acc["acc_id"]
    trd_env = 0       # 0=模拟盘（安全！）
    trd_market = 1    # 1=港股, 2=美股, 3=A股

    # 解锁交易 (TrdUnlockTrade, Proto 2005)
    # 真实盘必须解锁，模拟盘可以不用
    # pwd_md5: 交易密码的 MD5 哈希
    # security_firm: 1=富途证券(香港), 2=富途证券(美国), 3=富途证券(新加坡)
    #
    # 示例（请替换为你的实际密码）:
    # import hashlib
    # pwd_md5 = hashlib.md5("your_password".encode()).hexdigest()
    # client.unlock_trade(unlock=True, pwd_md5=pwd_md5, security_firm=1)

    # 订阅交易推送 (TrdSubAccPush, Proto 2210)
    # 订阅后可通过 push 接收订单状态变更和成交通知
    client.sub_acc_push(acc_ids=[acc_id])
    print(f"  已订阅账户 {acc_id} 的交易推送")

    # 查询资金 (TrdGetFunds, Proto 2101)
    funds = client.get_funds(trd_env=trd_env, acc_id=acc_id, trd_market=trd_market)
    print(f"\n  === 资金 ===")
    print(f"  总资产:   {funds.get('total_assets')}")
    print(f"  现金:     {funds.get('cash')}")
    print(f"  购买力:   {funds.get('power')}")
    print(f"  市值:     {funds.get('market_val')}")
    print(f"  冻结资金: {funds.get('frozen_cash')}")
    print(f"  币种:     {funds.get('currency')}")

    # 查询持仓 (TrdGetPositionList, Proto 2102)
    positions = client.get_position_list(
        trd_env=trd_env, acc_id=acc_id, trd_market=trd_market,
    )
    print(f"\n  === 持仓 ({len(positions)} 条) ===")
    for pos in positions[:5]:
        print(f"  {pos['code']}: qty={pos['qty']}, "
              f"cost={pos['cost_price']}, val={pos['val']}, "
              f"pl={pos['pl_val']} ({pos['pl_ratio']}%)")

    # 查询订单 (TrdGetOrderList, Proto 2201)
    orders = client.get_order_list(
        trd_env=trd_env, acc_id=acc_id, trd_market=trd_market,
    )
    print(f"\n  === 订单 ({len(orders)} 条) ===")
    for order in orders[:5]:
        print(f"  order_id={order['order_id']}, {order['code']}: "
              f"side={order['trd_side']}, qty={order['qty']}, "
              f"price={order['price']}, status={order['order_status']}")
        # trd_side: 1=买入, 2=卖出, 3=卖空, 4=买回
        # order_status: 0=未提交, 1=等待提交, 2=正在提交, 3=提交失败,
        #   5=已提交, 10=部分成交, 11=全部成交, 14=部分撤单, 15=全部撤单

    # 查询成交 (TrdGetOrderFillList, Proto 2211)
    # 注意：模拟盘可能不支持成交查询
    try:
        fills = client.get_order_fill_list(
            trd_env=trd_env, acc_id=acc_id, trd_market=trd_market,
        )
        print(f"\n  === 成交 ({len(fills)} 条) ===")
        for fill in fills[:5]:
            print(f"  fill_id={fill['fill_id']}, {fill['code']}: "
                  f"side={fill['trd_side']}, qty={fill['qty']}, price={fill['price']}")
    except Exception as e:
        print(f"\n  === 成交: {e} ===")

    # 下单 (TrdPlaceOrder, Proto 2202)
    # [注意] 以下使用模拟盘！请勿在真实盘中无确认地运行。
    print(f"\n  === 下单（模拟盘）===")
    result = client.place_order(
        trd_env=0,          # 0=模拟盘（重要！）
        acc_id=acc_id,
        trd_market=1,       # 1=港股
        trd_side=1,         # 1=买入, 2=卖出
        order_type=1,       # 1=普通限价单, 2=市价单, 5=竞价限价单, 6=竞价市价单
        code="00700",       # 证券代码
        qty=100.0,          # 数量
        price=300.0,        # 价格（市价单可不传）
        sec_market=1,       # TrdSecMarket: 1=港股, 2=美股, 31=沪股, 32=深股, 41=新加坡
    )
    order_id = result.get("order_id")
    print(f"  下单成功: order_id={order_id}, order_id_ex={result.get('order_id_ex')}")

    if order_id:
        # 改单 (TrdModifyOrder, Proto 2205)
        # modify_op: 1=正常改单, 2=撤单, 3=删除, 4=仅失效, 5=仅生效, 6=仅改价, 7=仅改量
        print(f"\n  === 改单 ===")
        client.modify_order(
            trd_env=0,
            acc_id=acc_id,
            trd_market=1,
            order_id=order_id,
            modify_op=1,       # 1=正常改单
            qty=200.0,         # 新数量
            price=295.0,       # 新价格
        )
        print(f"  改单成功: order_id={order_id}")

        # 撤单 (也通过 TrdModifyOrder)
        print(f"\n  === 撤单 ===")
        client.modify_order(
            trd_env=0,
            acc_id=acc_id,
            trd_market=1,
            order_id=order_id,
            modify_op=2,       # 2=撤单
        )
        print(f"  撤单成功: order_id={order_id}")

    # ------------------------------------------------------------------
    # 1.11 取消订阅 & 断开连接
    # ------------------------------------------------------------------
    # 取消订阅
    try:
        client.subscribe([(1, "00700")], [1, 2, 4], False)
        print("\n已取消订阅")
    except Exception as e:
        print(f"\n取消订阅: {e}")

    # 断开连接
    # disconnect() 会自动：
    #   - 中止所有推送转发任务
    #   - 清理推送 channel
    #   - 关闭 TCP 连接
    client.disconnect()
    print("已断开连接")
    print(f"断开后: is_connected = {client.is_connected()}")  # False


# ============================================================================
#  第二部分: NautilusTrader 集成
# ============================================================================
# 通过 TradingNode 框架使用 Futu 适配器。
# 这是生产环境推荐的使用方式，支持：
#   - 自动连接管理和共享连接（Data+Exec 共用一个 TCP 连接）
#   - 自动断线重连
#   - 实时行情推送 → NautilusTrader 数据类型自动转换
#   - 交易推送 → 订单/成交事件自动分发
#   - 策略订阅/下单的完整生命周期管理
# ============================================================================


def demo_nautilus_config():
    """
    演示 NautilusTrader 配置方式。

    NautilusTrader 集成分三步：
    1. 创建配置 (Config)
    2. 通过 TradingNode 注册工厂 (Factory)
    3. 编写策略 (Strategy) 订阅数据和交易
    """

    from nautilus_trader.config import InstrumentProviderConfig, TradingNodeConfig

    from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig

    # ------------------------------------------------------------------
    # 2.1 行情客户端配置
    # ------------------------------------------------------------------
    data_config = FutuDataClientConfig(
        # === 连接参数 ===
        host="127.0.0.1",       # Futu OpenD 地址
        port=11111,             # Futu OpenD 端口
        client_id="nautilus",   # 客户端标识
        client_ver=100,         # 客户端版本

        # === 复权类型 ===
        # 历史K线请求时的复权方式
        # 0 = 不复权 (原始价格)
        # 1 = 前复权 (默认，以最新价格为基准向前调整)
        # 2 = 后复权 (以上市价格为基准向后调整)
        rehab_type=1,

        # === 断线重连 ===
        reconnect=True,         # 是否自动重连（默认 True）
        reconnect_interval=5.0, # 重连间隔秒数（默认 5.0）
        # 重连逻辑：推送循环连续 5 次 poll 错误后触发
        # 断开 → 等待 reconnect_interval → 重新连接 → 重新注册推送

        # === Instrument Provider ===
        instrument_provider=InstrumentProviderConfig(),
    )

    # ------------------------------------------------------------------
    # 2.2 交易客户端配置
    # ------------------------------------------------------------------
    exec_config = FutuExecClientConfig(
        # === 连接参数（与行情相同即可共享连接）===
        host="127.0.0.1",
        port=11111,
        client_id="nautilus",
        client_ver=100,

        # === 交易环境 ===
        trd_env=0,              # 0=模拟盘, 1=真实盘
        acc_id=0,               # 账户 ID。0=自动选择第一个账户
        trd_market=1,           # 交易市场: 1=港股, 2=美股, 3=A股, 4=港股期权

        # === 交易解锁 ===
        # 真实盘必须提供交易密码的 MD5 哈希
        # 模拟盘可留空
        unlock_pwd_md5="",
        # 示例:
        # unlock_pwd_md5=hashlib.md5("your_password".encode()).hexdigest(),

        # === 断线重连 ===
        reconnect=True,
        reconnect_interval=5.0,

        instrument_provider=InstrumentProviderConfig(),
    )

    print("=== 配置创建成功 ===")
    print(f"  Data: {data_config.host}:{data_config.port}, "
          f"rehab_type={data_config.rehab_type}, "
          f"reconnect={data_config.reconnect}")
    print(f"  Exec: trd_env={exec_config.trd_env}, "
          f"trd_market={exec_config.trd_market}, "
          f"acc_id={exec_config.acc_id}")

    return data_config, exec_config


def demo_nautilus_node():
    """
    演示通过 TradingNode 启动完整的交易系统。

    架构说明:
      TradingNode
       ├── FutuLiveDataClient     ← 行情（报价/K线/盘口/逐笔推送）
       ├── FutuLiveExecutionClient ← 交易（下单/撤单/订单推送/成交推送）
       └── MyStrategy              ← 用户策略

    连接共享:
      当 DataConfig 和 ExecConfig 的 (host, port) 相同时，
      工厂自动共享同一个 PyFutuClient 实例（同一条 TCP 连接）。
      这避免了 Futu OpenD 的并发连接数限制。
    """

    from nautilus_trader.config import (
        InstrumentProviderConfig,
        LiveDataEngineConfig,
        LiveExecEngineConfig,
        TradingNodeConfig,
    )
    from nautilus_trader.live.node import TradingNode

    from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig
    from nautilus_futu.factories import FutuLiveDataClientFactory, FutuLiveExecClientFactory

    # ------------------------------------------------------------------
    # 2.3 TradingNode 配置
    # ------------------------------------------------------------------
    node_config = TradingNodeConfig(
        data_clients={
            "FUTU": FutuDataClientConfig(
                host="127.0.0.1",
                port=11111,
                rehab_type=1,
                reconnect=True,
                reconnect_interval=5.0,
            ),
        },
        exec_clients={
            "FUTU": FutuExecClientConfig(
                host="127.0.0.1",      # 与 data_client 相同 → 共享连接
                port=11111,             # 与 data_client 相同 → 共享连接
                trd_env=0,              # 模拟盘
                trd_market=1,           # 港股
            ),
        },
    )

    # ------------------------------------------------------------------
    # 2.4 创建节点并注册工厂
    # ------------------------------------------------------------------
    node = TradingNode(config=node_config)

    # 注册客户端工厂
    # NautilusTrader 通过工厂模式创建客户端实例
    # 工厂内部调用 _get_shared_client() 实现连接共享
    node.add_data_client_factory("FUTU", FutuLiveDataClientFactory)
    node.add_exec_client_factory("FUTU", FutuLiveExecClientFactory)

    # ------------------------------------------------------------------
    # 2.5 添加策略
    # ------------------------------------------------------------------
    # 参见下方 demo_strategy() 中的策略示例
    # node.trader.add_strategy(MyStrategy(config=...))

    # ------------------------------------------------------------------
    # 2.6 构建并运行
    # ------------------------------------------------------------------
    node.build()
    # node.run()  # 启动事件循环（阻塞直到 Ctrl+C）

    print("TradingNode 已构建（未启动）")
    print("调用 node.run() 将启动事件循环")

    # node.run() 内部流程:
    #   1. DataClient._connect():
    #      - 连接 OpenD（或复用已有连接）
    #      - 注册行情推送 (proto 3005/3011/3013/3007)
    #      - 启动推送轮询循环
    #   2. ExecClient._connect():
    #      - 复用 DataClient 的连接
    #      - 获取/自动选择账户
    #      - 解锁交易（如有密码）
    #      - 订阅交易推送 (sub_acc_push)
    #      - 注册交易推送 (proto 2208/2218) — 追加到同一 channel
    #      - 启动交易推送轮询循环
    #   3. 策略启动:
    #      - on_start() 中订阅行情
    #      - 收到行情推送后触发 on_quote_tick/on_trade_tick/on_bar 等回调

    node.dispose()


def demo_strategy():
    """
    演示策略中使用 Futu 适配器的典型模式。

    以下是一个完整的策略骨架，展示了所有可用的数据订阅和交易操作。
    """

    # 以下代码展示策略结构，不可直接运行（需要在 TradingNode 中注册）
    strategy_code = '''
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, QuoteTick, TradeTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import MarketOrder, LimitOrder
from nautilus_trader.trading.strategy import Strategy


class FutuExampleStrategyConfig(StrategyConfig):
    """策略配置"""
    instrument_id: str = "00700.HKEX"   # 证券标识 = "{code}.{venue}"
    bar_type: str = "00700.HKEX-1-MINUTE-LAST-EXTERNAL"  # K线类型


class FutuExampleStrategy(Strategy):
    """
    Futu 适配器功能演示策略。

    覆盖以下功能:
    - 订阅实时报价 (QuoteTick)
    - 订阅逐笔成交 (TradeTick)
    - 订阅盘口深度 (OrderBookDeltas)
    - 订阅K线推送 (Bar)
    - 请求历史K线
    - 下限价单/市价单
    - 改单/撤单
    """

    def __init__(self, config: FutuExampleStrategyConfig) -> None:
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)

    def on_start(self) -> None:
        """策略启动时订阅数据。"""

        # --- 订阅实时行情 ---

        # 订阅报价 (QuoteTick)
        # 对应 Futu SubType=1 (Basic)
        # 推送 proto_id=3005，包含最新价/开高低/成交量等
        self.subscribe_quote_ticks(self.instrument_id)

        # 订阅逐笔成交 (TradeTick)
        # 对应 Futu SubType=4 (Ticker)
        # 推送 proto_id=3011，包含每笔成交价/量/方向
        self.subscribe_trade_ticks(self.instrument_id)

        # 订阅盘口深度 (OrderBookDeltas)
        # 对应 Futu SubType=2 (OrderBook)
        # 推送 proto_id=3013，包含买卖盘各档价/量
        self.subscribe_order_book_deltas(self.instrument_id)

        # 订阅K线推送 (Bar)
        # 对应 Futu SubType=11 (KL_1Min)
        # 推送 proto_id=3007，包含K线 OHLCV
        # 支持: 1分钟/5分钟/15分钟/30分钟/60分钟/日线
        self.subscribe_bars(self.bar_type)

        # --- 请求历史数据 ---

        # 请求历史K线
        # 内部调用 get_history_kl (Proto 3103)
        # rehab_type 由 FutuDataClientConfig.rehab_type 控制
        from datetime import datetime, timezone
        self.request_bars(
            self.bar_type,
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 31, tzinfo=timezone.utc),
        )

        # 请求证券定义
        # 内部调用 get_static_info (Proto 3202)
        self.request_instrument(self.instrument_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """收到报价推送回调。"""
        self.log.info(
            f"QuoteTick: bid={tick.bid_price}x{tick.bid_size}, "
            f"ask={tick.ask_price}x{tick.ask_size}"
        )

    def on_trade_tick(self, tick: TradeTick) -> None:
        """收到逐笔成交推送回调。"""
        self.log.info(
            f"TradeTick: price={tick.price}, size={tick.size}, "
            f"aggressor={tick.aggressor_side}"
        )

    def on_bar(self, bar: Bar) -> None:
        """收到K线推送或历史K线回调。"""
        self.log.info(
            f"Bar: O={bar.open}, H={bar.high}, L={bar.low}, "
            f"C={bar.close}, V={bar.volume}"
        )

        # --- 交易示例 ---
        # [注意] 以下仅为演示，请勿直接用于实盘

        # 下限价买单
        limit_order = self.order_factory.limit(
            instrument_id=self.instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(100),
            price=Price.from_str("300.000"),
            time_in_force=TimeInForce.DAY,
        )
        self.submit_order(limit_order)

        # 下市价卖单
        market_order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_int(100),
        )
        self.submit_order(market_order)

    def on_order_accepted(self, event) -> None:
        """订单被接受。"""
        self.log.info(f"Order accepted: {event.venue_order_id}")

        # 改单示例：修改价格和数量
        # self.modify_order(order, quantity=Quantity.from_int(200), price=Price.from_str("295.000"))

        # 撤单示例
        # self.cancel_order(order)

    def on_order_filled(self, event) -> None:
        """订单成交。"""
        self.log.info(
            f"Order filled: {event.venue_order_id}, "
            f"qty={event.last_qty}, px={event.last_px}"
        )

    def on_order_canceled(self, event) -> None:
        """订单已撤销。"""
        self.log.info(f"Order canceled: {event.venue_order_id}")

    def on_order_rejected(self, event) -> None:
        """订单被拒绝。"""
        self.log.info(f"Order rejected: {event.reason}")

    def on_stop(self) -> None:
        """策略停止时取消所有订阅。"""
        # 取消订阅
        self.unsubscribe_quote_ticks(self.instrument_id)
        self.unsubscribe_trade_ticks(self.instrument_id)
        self.unsubscribe_order_book_deltas(self.instrument_id)
        self.unsubscribe_bars(self.bar_type)

        # 撤销所有未成交订单
        self.cancel_all_orders(self.instrument_id)
'''
    print("=== 策略代码 ===")
    print(strategy_code)


# ============================================================================
#  第三部分: 连接共享机制说明
# ============================================================================


def demo_connection_sharing():
    """
    演示连接共享机制。

    当 DataClient 和 ExecClient 连接到同一个 Futu OpenD (相同 host:port) 时，
    它们共享同一个 PyFutuClient 实例和 TCP 连接。

    这解决了 Futu OpenD 的并发连接数限制问题。
    """

    from nautilus_futu.factories import _get_shared_client, _shared_clients

    # 清空缓存（仅演示用）
    _shared_clients.clear()

    # 相同 (host, port) 返回同一个实例
    client_a = _get_shared_client("127.0.0.1", 11111)
    client_b = _get_shared_client("127.0.0.1", 11111)
    assert client_a is client_b, "应该是同一个实例"
    print("client_a is client_b:", client_a is client_b)  # True

    # 不同 port 返回不同实例
    client_c = _get_shared_client("127.0.0.1", 22222)
    assert client_a is not client_c, "应该是不同实例"
    print("client_a is client_c:", client_a is not client_c)  # True

    print(f"共享缓存中的客户端数: {len(_shared_clients)}")  # 2

    _shared_clients.clear()


# ============================================================================
#  第四部分: 市场代码速查表
# ============================================================================


def print_reference_tables():
    """打印所有常量和代码映射速查表。"""

    print("""
╔══════════════════════════════════════════════════════════════╗
║                  nautilus-futu 代码速查表                     ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  === QotMarket（行情市场代码）===                              ║
║  1  = 港股                                                   ║
║  2  = 港股期货                                                ║
║  11 = 美股                                                   ║
║  21 = 沪股通                                                  ║
║  22 = 深股通                                                  ║
║  31 = 新加坡                                                  ║
║                                                              ║
║  === TrdSecMarket（交易市场代码，与 QotMarket 不同！）===       ║
║  1  = 港股                                                   ║
║  2  = 美股                                                   ║
║  31 = 沪股                                                   ║
║  32 = 深股                                                   ║
║  41 = 新加坡                                                  ║
║                                                              ║
║  === TrdMarket（交易大市场）===                                ║
║  1 = 港股    2 = 美股    3 = A股    4 = 港股期权               ║
║                                                              ║
║  === Venue 映射 ===                                           ║
║  HKEX    <-> QotMarket 1/2  <-> TrdSecMarket 1                  ║
║  NYSE    <-> QotMarket 11   <-> TrdSecMarket 2                  ║
║  NASDAQ  <-> QotMarket 11   <-> TrdSecMarket 2                  ║
║  SSE     <-> QotMarket 21   <-> TrdSecMarket 31                 ║
║  SZSE    <-> QotMarket 22   <-> TrdSecMarket 32                 ║
║  SGX     <-> QotMarket 31   <-> TrdSecMarket 41                 ║
║                                                              ║
║  === SubType（订阅类型）===                                    ║
║  1  = Basic (报价)       2  = OrderBook (盘口)                ║
║  4  = Ticker (逐笔)      5  = RT (分时)                      ║
║  6  = KL_Day (日K)       7  = KL_5Min (5分K)                 ║
║  8  = KL_15Min           9  = KL_30Min                       ║
║  10 = KL_60Min           11 = KL_1Min (1分K)                 ║
║                                                              ║
║  === KLType（K线类型，用于历史K线请求）===                       ║
║  1 = 1分钟    2 = 日线    3 = 周线    4 = 月线                 ║
║  6 = 5分钟    7 = 15分钟   8 = 30分钟   9 = 60分钟             ║
║                                                              ║
║  === RehabType（复权类型）===                                   ║
║  0 = 不复权   1 = 前复权   2 = 后复权                           ║
║                                                              ║
║  === TrdSide（交易方向）===                                     ║
║  1 = 买入    2 = 卖出    3 = 卖空    4 = 买回                  ║
║                                                              ║
║  === OrderType（订单类型）===                                   ║
║  1 = 普通限价单  2 = 市价单  5 = 竞价限价单  6 = 竞价市价单      ║
║                                                              ║
║  === TrdEnv（交易环境）===                                      ║
║  0 = 模拟盘    1 = 真实盘                                      ║
║                                                              ║
║  === OrderStatus（订单状态）===                                  ║
║  0  = 未提交        -1  = 未知           1  = 等待提交          ║
║  2  = 正在提交       3  = 提交失败        4  = 超时             ║
║  5  = 已提交         10 = 部分成交        11 = 全部成交          ║
║  12 = 正在撤单(部分) 13 = 正在撤单(全部)   14 = 部分撤单         ║
║  15 = 全部撤单       21 = 失败            22 = 已失效           ║
║  23 = 已删除         24 = 成交后撤单                            ║
║                                                              ║
║  === Proto ID 速查 ===                                        ║
║  1001 = InitConnect     1002 = GetGlobalState                ║
║  1004 = KeepAlive       2001 = TrdGetAccList                 ║
║  2005 = TrdUnlockTrade  2101 = TrdGetFunds                   ║
║  2102 = TrdGetPositionList  2201 = TrdGetOrderList            ║
║  2202 = TrdPlaceOrder   2205 = TrdModifyOrder                ║
║  2208 = TrdUpdateOrder(推送)  2210 = TrdSubAccPush            ║
║  2211 = TrdGetOrderFillList   2218 = TrdUpdateOrderFill(推送)  ║
║  3001 = Qot_Sub         3004 = Qot_GetBasicQot               ║
║  3005 = Qot_UpdateBasicQot(推送)                               ║
║  3006 = Qot_GetKL       3007 = Qot_UpdateKL(推送)             ║
║  3010 = Qot_GetTicker   3011 = Qot_UpdateTicker(推送)         ║
║  3012 = Qot_GetOrderBook  3013 = Qot_UpdateOrderBook(推送)    ║
║  3103 = Qot_RequestHistoryKL                                  ║
║  3202 = Qot_GetStaticInfo   3203 = Qot_GetSecuritySnapshot   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


# ============================================================================
#  主程序
# ============================================================================


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("  nautilus-futu 完整功能示例")
    print("=" * 60)
    print()

    # 默认只运行不需要 OpenD 的部分
    if "--all" in sys.argv:
        # 需要 Futu OpenD 运行
        print("[第一部分] PyFutuClient 底层 API")
        print("-" * 40)
        try:
            demo_rust_client()
        except Exception as e:
            print(f"错误: {e}")
            print("请确保 Futu OpenD 正在运行 (127.0.0.1:11111)")
        print()

    print("[第二部分] NautilusTrader 配置")
    print("-" * 40)
    demo_nautilus_config()
    print()

    if "--node" in sys.argv:
        print("[第二部分续] TradingNode 构建")
        print("-" * 40)
        try:
            demo_nautilus_node()
        except Exception as e:
            print(f"错误: {e}")
        print()

    print("[第三部分] 连接共享机制")
    print("-" * 40)
    demo_connection_sharing()
    print()

    print("[第四部分] 策略示例代码")
    print("-" * 40)
    demo_strategy()
    print()

    print("[附录] 代码速查表")
    print("-" * 40)
    print_reference_tables()

    print("=" * 60)
    print("  运行参数:")
    print("    --all   启动完整演示（需要 Futu OpenD）")
    print("    --node  构建 TradingNode（需要 nautilus_trader）")
    print("=" * 60)
