"""
Minimal example: Connect to Futu OpenD and subscribe to market data.

Prerequisites:
    1. Futu OpenD gateway running locally (default port 11111)
    2. Install: `maturin develop` (to build the Rust extension)
    3. Install: `pip install nautilus_trader`

Usage:
    python examples/live_market_data.py
"""

import asyncio

from nautilus_futu.config import FutuDataClientConfig
from nautilus_futu.constants import FUTU_VENUE


async def main():
    """Run the example."""
    # Configure the data client
    config = FutuDataClientConfig(
        host="127.0.0.1",
        port=11111,
        client_id="nautilus_example",
        client_ver=100,
    )

    print(f"Futu Data Client Config:")
    print(f"  Host: {config.host}")
    print(f"  Port: {config.port}")
    print(f"  Client ID: {config.client_id}")
    print(f"  Venue: {FUTU_VENUE}")
    print()

    # NOTE: To actually connect and receive data, you need:
    # 1. Futu OpenD running
    # 2. The Rust extension built (`maturin develop`)
    # 3. A valid Futu account

    # Example: Using the low-level Rust client directly
    try:
        from nautilus_futu._rust import FutuClient

        client = FutuClient()
        client.connect(config.host, config.port, config.client_id, config.client_ver)
        print("Connected to Futu OpenD!")

        # Subscribe to HK stock basic quote
        client.subscribe(
            securities=[(1, "00700")],  # Tencent
            sub_types=[1],  # Basic quote
            is_sub=True,
        )
        print("Subscribed to 00700.HK basic quote")

        # Get basic quote
        quotes = client.get_basic_qot(securities=[(1, "00700")])
        for q in quotes:
            print(f"Quote: {q}")

        # Get historical daily K-lines
        klines = client.get_history_kl(
            market=1,
            code="00700",
            kl_type=2,  # Day
            begin_time="2024-01-01",
            end_time="2024-01-31",
            max_count=30,
        )
        print(f"Got {len(klines)} historical K-lines")
        for kl in klines[:3]:
            print(f"  {kl}")

        client.disconnect()
        print("Disconnected")

    except ImportError:
        print("Rust extension not built. Run 'maturin develop' first.")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure Futu OpenD is running on 127.0.0.1:11111")


if __name__ == "__main__":
    asyncio.run(main())
