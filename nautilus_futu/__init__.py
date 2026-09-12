"""Futu OpenD adapter for NautilusTrader."""

__version__ = "0.5.1"


def __getattr__(name):
    """Lazy imports to avoid requiring nautilus_trader at import time."""
    _imports = {
        "FutuDataClientConfig": "nautilus_futu.config",
        "FutuExecClientConfig": "nautilus_futu.config",
        "FUTU_VENUE": "nautilus_futu.constants",
        "FutuConnectionManager": "nautilus_futu.connection",
        "FutuLiveDataClient": "nautilus_futu.data",
        "FutuLiveExecutionClient": "nautilus_futu.execution",
        "FutuLiveDataClientFactory": "nautilus_futu.factories",
        "FutuLiveExecClientFactory": "nautilus_futu.factories",
        "FutuInstrumentProvider": "nautilus_futu.providers",
    }
    if name in _imports:
        import importlib

        module = importlib.import_module(_imports[name])
        return getattr(module, name)
    raise AttributeError(f"module 'nautilus_futu' has no attribute {name!r}")


__all__ = [
    "FUTU_VENUE",
    "FutuConnectionManager",
    "FutuDataClientConfig",
    "FutuExecClientConfig",
    "FutuInstrumentProvider",
    "FutuLiveDataClient",
    "FutuLiveDataClientFactory",
    "FutuLiveExecClientFactory",
    "FutuLiveExecutionClient",
]
