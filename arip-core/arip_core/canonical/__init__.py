"""Canonical telemetry layer.

Rules read ARIP-canonical signals via :class:`Signals`, not raw
attribute keys. The mapping between raw telemetry conventions
(``order.id`` vs ``orderId`` vs ``order_id``; ``retry.attempt`` vs
``http.retry_count``; …) and the canonical signals is driven by
:class:`NormalizationConfig`. A customer onboards a new environment
by writing a config, not new rules.
"""

from .config import NormalizationConfig, load_config_yaml
from .signals import PoolStats, Signals, StateTransition

__all__ = [
    "NormalizationConfig",
    "PoolStats",
    "Signals",
    "StateTransition",
    "load_config_yaml",
]
