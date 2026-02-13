"""Comprehensive test for Futu OpenD adapter (pip installed version)."""
import time
from nautilus_futu._rust import PyFutuClient

PASS = "[PASS]"
FAIL = "[FAIL]"

def main():
    print("=" * 60)
    print("Futu OpenD Adapter - Live Test")
    print("=" * 60)

    client = PyFutuClient()
    results = []

    # ── 1. Connect ──────────────────────────────────────────────
    print("\n[1] Connecting to Futu OpenD (127.0.0.1:11111)...")
    try:
        client.connect("127.0.0.1", 11111, "test", 100)
        print(f"    {PASS} Connected!")
        results.append(("Connect", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Connect", False))
        return results  # can't continue without connection

    # ── 2. Get account list ─────────────────────────────────────
    print("\n[2] Getting account list...")
    try:
        accounts = client.get_acc_list()
        print(f"    {PASS} Got {len(accounts)} accounts:")
        for acc in accounts[:5]:
            env_name = {0: "REAL", 1: "SIMULATE"}.get(acc["trd_env"], str(acc["trd_env"]))
            markets = acc.get("trd_market_auth_list", [])
            print(f"      acc_id={acc['acc_id']}  env={env_name}  markets={markets}")
        if len(accounts) > 5:
            print(f"      ... and {len(accounts) - 5} more")
        results.append(("Get accounts", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Get accounts", False))

    # Pick a simulate account that supports HK market (trd_market=1)
    sim_acc = None
    for acc in accounts:
        markets = acc.get("trd_market_auth_list", [])
        if acc["trd_env"] == 1 and 1 in markets:  # SIMULATE + HK
            sim_acc = acc
            break
    if not sim_acc:
        # Fallback: any simulate account
        for acc in accounts:
            if acc["trd_env"] == 1:
                sim_acc = acc
                break

    # ── 3. Subscribe (HK market=1, 00700=Tencent) ──────────────
    print("\n[3] Subscribing to 00700.HK (Quote + KL_Day)...")
    try:
        # SubType: 1=Quote, 6=KL_Day
        client.subscribe([(1, "00700")], [1, 6], True)
        print(f"    {PASS} Subscribed!")
        results.append(("Subscribe", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Subscribe", False))

    # ── 4. Get static info ──────────────────────────────────────
    print("\n[4] Getting static info (00700.HK, 09988.HK)...")
    try:
        infos = client.get_static_info([(1, "00700"), (1, "09988")])
        print(f"    {PASS} Got {len(infos)} securities:")
        for info in infos:
            print(f"      {info['code']}: name={info['name']}, "
                  f"lot_size={info['lot_size']}, sec_type={info['sec_type']}, "
                  f"list_time={info['list_time']}")
        results.append(("Static info", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Static info", False))

    # ── 5. Get basic quote ──────────────────────────────────────
    print("\n[5] Getting basic quote (00700.HK)...")
    try:
        quotes = client.get_basic_qot([(1, "00700")])
        print(f"    {PASS} Got {len(quotes)} quotes:")
        for q in quotes:
            print(f"      {q['code']}: price={q['cur_price']}, "
                  f"open={q['open_price']}, high={q['high_price']}, "
                  f"low={q['low_price']}, vol={q['volume']}, "
                  f"turnover={q['turnover']}")
        results.append(("Basic quote", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Basic quote", False))

    # ── 6. Get history K-line ───────────────────────────────────
    print("\n[6] Getting history K-line (00700.HK, daily, last 5)...")
    try:
        klines = client.get_history_kl(
            1, "00700",     # market, code
            1,              # rehab_type: 1=forward adjust
            1,              # kl_type: 1=Day
            "2025-01-01",   # begin
            "2026-12-31",   # end
            5,              # max 5 bars
        )
        print(f"    {PASS} Got {len(klines)} K-lines:")
        for kl in klines:
            print(f"      {kl['time']}: O={kl['open_price']:.2f} "
                  f"H={kl['high_price']:.2f} L={kl['low_price']:.2f} "
                  f"C={kl['close_price']:.2f} V={kl['volume']}")
        results.append(("History KL", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("History KL", False))

    # ── 7. Multi-stock quote (09988.HK = Alibaba) ───────────────
    print("\n[7] Subscribing to 09988.HK (Alibaba)...")
    try:
        client.subscribe([(1, "09988")], [1], True)
        time.sleep(0.3)
        quotes = client.get_basic_qot([(1, "09988")])
        print(f"    {PASS} Got {len(quotes)} quotes:")
        for q in quotes:
            print(f"      {q['code']}: price={q['cur_price']}, "
                  f"open={q['open_price']}, high={q['high_price']}, "
                  f"low={q['low_price']}, vol={q['volume']}")
        results.append(("Multi-stock quote", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Multi-stock quote", False))

    # ── 8. Simulate trade (unlock + place + cancel) ──────────────
    if sim_acc:
        print(f"\n[8] Simulate trade test (acc_id={sim_acc['acc_id']})...")
        try:
            # Unlock trade first (change to your real trade password)
            import hashlib
            pwd_md5 = hashlib.md5(b"123456").hexdigest()
            client.unlock_trade(True, pwd_md5)
            print(f"    Trade unlocked!")

            # Place a limit buy order for 00700.HK at a very low price
            # trd_market: 1=HK, trd_side: 1=Buy, order_type: 2=Limit
            order = client.place_order(
                1,                      # trd_env: SIMULATE
                sim_acc["acc_id"],      # acc_id
                1,                      # trd_market: HK
                1,                      # trd_side: Buy
                2,                      # order_type: Limit (Normal)
                "00700",                # code
                100,                    # qty (1 lot)
                100.0,                  # price (very low, won't fill)
                1,                      # sec_market: HK
            )
            order_id = order.get("order_id", 0)
            print(f"    {PASS} Order placed: id={order_id}, id_ex={order.get('order_id_ex', '')}")

            # Cancel the order (modify_op: 4=Cancel)
            time.sleep(0.5)
            client.modify_order(
                1,                      # trd_env: SIMULATE
                sim_acc["acc_id"],      # acc_id
                1,                      # trd_market: HK
                order_id,               # order_id
                4,                      # modify_op: Cancel
            )
            print(f"    {PASS} Order cancelled!")
            results.append(("Place+Cancel order", True))
        except Exception as e:
            print(f"    {FAIL} {e}")
            results.append(("Place+Cancel order", False))
    else:
        print("\n[8] Skipped: no simulate account found")
        results.append(("Place+Cancel order", None))

    # ── 9. Disconnect ───────────────────────────────────────────
    print("\n[9] Disconnecting...")
    try:
        client.disconnect()
        print(f"    {PASS} Disconnected!")
        results.append(("Disconnect", True))
    except Exception as e:
        print(f"    {FAIL} {e}")
        results.append(("Disconnect", False))

    # ── Summary ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Summary:")
    print("-" * 40)
    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    skipped = sum(1 for _, r in results if r is None)
    for name, r in results:
        status = PASS if r is True else (FAIL if r is False else "[SKIP]")
        print(f"  {status} {name}")
    print("-" * 40)
    print(f"  {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    return results


if __name__ == "__main__":
    main()
