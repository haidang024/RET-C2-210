"""PB-7 is conditional and not applicable to this non-HITL template."""

from pathlib import Path

import pytest
import yaml

_CONFIG_PATH = Path(__file__).parents[2] / "config" / "config.yaml"
_CONFIG = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
_HITL_ENABLED = bool(_CONFIG.get("hitl", {}).get("enabled", False))

pytestmark = pytest.mark.skipif(
    not _HITL_ENABLED,
    reason="config/config.yaml sets hitl.enabled: false — PB-7 not applicable",
)


def test_pb7_hitl_interrupt_propagates() -> None:
    pytest.fail("HITL became enabled; add a real GraphInterrupt propagation fixture before release")


def test_pb7_hitl_allowed_false_skips_interrupt() -> None:
    pytest.fail("HITL became enabled; add a hitl_allowed=False guard fixture before release")
