"""Test script for live Futu OpenD connection."""
from nautilus_futu._rust import PyFutuClient


def main():
    client = PyFutuClient()

    # 1. 连接 OpenD
    print("=" * 50)
    print("1. 连接 Futu OpenD...")
    try:
        client.connect("127.0.0.1", 11111, "nautilus-test", 100)
        print("   连接成功!")
    except Exception as e:
        print(f"   连接失败: {e}")
        return

    # 2. 获取账户列表
    print("\n" + "=" * 50)
    print("2. 获取账户列表...")
    try:
        accounts = client.get_acc_list()
        for acc in accounts:
            print(f"   账户ID: {acc['acc_id']}, 环境: {'模拟' if acc['trd_env'] == 0 else '真实'}, 市场: {acc.get('trd_market_auth_list', [])}")
    except Exception as e:
        print(f"   获取失败: {e}")

    # 3. 获取静态信息（腾讯 00700 + 阿里 09988）
    print("\n" + "=" * 50)
    print("3. 获取港股静态信息...")
    try:
        infos = client.get_static_info([(1, "00700"), (1, "09988")])
        for info in infos:
            print(f"   {info['code']} {info['name']} | 每手: {info['lot_size']}股 | 类型: {info['sec_type']}")
    except Exception as e:
        print(f"   获取失败: {e}")

    # 4. 获取实时报价
    print("\n" + "=" * 50)
    print("4. 获取实时报价...")
    try:
        # 先订阅
        client.subscribe([(1, "00700"), (1, "09988")], [1], True)  # SubType 1 = Quote
        quotes = client.get_basic_qot([(1, "00700"), (1, "09988")])
        for q in quotes:
            print(f"   {q['code']}: 最新价={q['cur_price']}, "
                  f"开={q['open_price']}, 高={q['high_price']}, "
                  f"低={q['low_price']}, 昨收={q['last_close_price']}, "
                  f"成交量={q['volume']}")
    except Exception as e:
        print(f"   获取失败: {e}")

    # 5. 获取历史日K线
    print("\n" + "=" * 50)
    print("5. 获取腾讯最近5根日K线...")
    try:
        bars = client.get_history_kl(
            market=1,
            code="00700",
            rehab_type=1,      # 前复权
            kl_type=1,          # 日K
            begin_time="2025-01-01",
            end_time="2026-12-31",
            max_count=5,
        )
        for bar in bars:
            print(f"   {bar['time']}: 开={bar['open_price']}, 高={bar['high_price']}, "
                  f"低={bar['low_price']}, 收={bar['close_price']}, 量={bar['volume']}")
    except Exception as e:
        print(f"   获取失败: {e}")

    # 6. 断开连接
    print("\n" + "=" * 50)
    print("6. 断开连接...")
    client.disconnect()
    print("   已断开")
    print("\n测试完成!")


if __name__ == "__main__":
    main()
