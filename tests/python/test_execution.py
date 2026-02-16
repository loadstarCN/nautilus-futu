"""Tests for execution client account balance logic."""

from __future__ import annotations

from nautilus_trader.model.objects import Currency

from nautilus_futu.execution import parse_funds_to_balance


USD = Currency.from_str("USD")
HKD = Currency.from_str("HKD")
CNY = Currency.from_str("CNY")


# ─────────────────────────────────────────────────────────
# Bug 1: free/locked 字段反转
# ─────────────────────────────────────────────────────────


class TestFreeLockedFixed:
    """验证 free/locked 使用 frozen_cash 而非 available_funds。"""

    def test_正常账户_free等于total减frozen(self):
        """total_assets=10000, frozen_cash=500 → free=9500, locked=500。"""
        funds = {
            "total_assets": 10000.0,
            "cash": 8000.0,
            "frozen_cash": 500.0,
            "available_funds": None,
        }
        b = parse_funds_to_balance(funds, USD)

        assert float(b.total) == 10000.0
        assert float(b.free) == 9500.0
        assert float(b.locked) == 500.0
        assert str(b.currency) == "USD"

    def test_无冻结资金_free等于total(self):
        """frozen_cash=0 时，free 应等于 total（非 0）。"""
        funds = {
            "total_assets": 4173.12,
            "cash": 4173.12,
            "frozen_cash": 0.0,
            "available_funds": None,
        }
        b = parse_funds_to_balance(funds, USD)

        assert float(b.free) == 4173.12
        assert float(b.locked) == 0.0

    def test_available_funds为None不影响结果(self):
        """available_funds=None 时不应导致 free=0。

        这是 Bug 1 的核心回归测试：旧代码中 dict.get("available_funds", fallback)
        返回 None（key 存在但值为 None），导致 free=0。
        """
        funds = {
            "total_assets": 5000.0,
            "cash": 5000.0,
            "frozen_cash": 0.0,
            "available_funds": None,
        }
        b = parse_funds_to_balance(funds, USD)

        # 旧代码: free=0, locked=5000 (错误)
        # 新代码: free=5000, locked=0 (正确)
        assert float(b.free) == 5000.0
        assert float(b.locked) == 0.0

    def test_frozen_cash为None时默认为0(self):
        """frozen_cash=None 时应视为 0。"""
        funds = {
            "total_assets": 3000.0,
            "cash": 3000.0,
            "frozen_cash": None,
            "available_funds": None,
        }
        b = parse_funds_to_balance(funds, USD)

        assert float(b.free) == 3000.0
        assert float(b.locked) == 0.0

    def test_HKD货币(self):
        """HKD 货币应正确标记。"""
        funds = {
            "total_assets": 100000.0,
            "cash": 80000.0,
            "frozen_cash": 5000.0,
        }
        b = parse_funds_to_balance(funds, HKD)

        assert str(b.currency) == "HKD"
        assert float(b.total) == 100000.0
        assert float(b.locked) == 5000.0
        assert float(b.free) == 95000.0

    def test_CNY货币(self):
        """CNY 货币应正确标记。"""
        funds = {
            "total_assets": 50000.0,
            "cash": 50000.0,
            "frozen_cash": 0.0,
        }
        b = parse_funds_to_balance(funds, CNY)

        assert str(b.currency) == "CNY"


# ─────────────────────────────────────────────────────────
# 边界情况
# ─────────────────────────────────────────────────────────


class TestParseBalanceEdgeCases:
    """边界情况测试。"""

    def test_total_assets缺失时默认为0(self):
        """total_assets 字段不在返回中时应默认 0。"""
        funds = {"cash": 100.0, "frozen_cash": 0.0}
        b = parse_funds_to_balance(funds, USD)

        assert float(b.total) == 0.0

    def test_frozen_cash缺失时默认为0(self):
        """frozen_cash 字段不在返回中时应默认 0。"""
        funds = {"total_assets": 1000.0, "cash": 1000.0}
        b = parse_funds_to_balance(funds, USD)

        assert float(b.locked) == 0.0
        assert float(b.free) == 1000.0

    def test_空字典返回零余额(self):
        """空 funds 字典应返回全零余额。"""
        b = parse_funds_to_balance({}, USD)

        assert float(b.total) == 0.0
        assert float(b.free) == 0.0
        assert float(b.locked) == 0.0

    def test_AccountBalance约束_total等于free加locked(self):
        """NautilusTrader 要求 total - locked == free。"""
        funds = {
            "total_assets": 8000.0,
            "cash": 6000.0,
            "frozen_cash": 1234.56,
        }
        b = parse_funds_to_balance(funds, USD)

        # NautilusTrader 核心约束: total - locked == free
        assert abs(float(b.total) - float(b.locked) - float(b.free)) < 0.001

    def test_Issue2场景_USD4173无冻结(self):
        """复现 Issue #2 的具体场景：USD 4173.12，无冻结。"""
        funds = {
            "total_assets": 4173.12,
            "cash": 4173.12,
            "frozen_cash": 0.0,
            "market_val": 0.0,
            "available_funds": None,  # 证券账户，此字段为 None
            "power": 4173.12,
            "avl_withdrawal_cash": 4173.12,
        }
        b = parse_funds_to_balance(funds, USD)

        # 修复前: free=0, locked=4173.12 (错误)
        # 修复后: free=4173.12, locked=0 (正确)
        assert float(b.total) == 4173.12
        assert float(b.free) == 4173.12
        assert float(b.locked) == 0.0
