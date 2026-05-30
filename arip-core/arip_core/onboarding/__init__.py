"""Onboarding helpers — drive `arip init` and `arip doctor`.

The point of this package is to take a *real sample* of an operator's
telemetry and either (a) emit a NormalizationConfig YAML they can
commit, or (b) explain rule-by-rule what would and wouldn't fire and
why. Both replace the "read 4 docs + edit a YAML by hand" onboarding
that used to be the only path.

Built directly from observed bundle shape — no speculation, no
"recommended" values disconnected from the operator's actual data.
"""

from __future__ import annotations

from .auto_config import detect_config, render_yaml
from .bundle_loader import iter_bundles, load_correlated
from .doctor import diagnose, render_doctor_report

__all__ = [
    "detect_config",
    "diagnose",
    "iter_bundles",
    "load_correlated",
    "render_doctor_report",
    "render_yaml",
]
