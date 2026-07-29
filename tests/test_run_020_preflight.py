from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path


PREFLIGHT_PATH = Path(
    "runs/h1_open_loop/dac_manual_sweep/run_020/run_020_preflight.py"
)


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("run_020_preflight", PREFLIGHT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fc0_readiness_is_waited_for_instead_of_static_preflight_failure() -> None:
    preflight = _load_preflight_module()

    transient_readiness_keys = {
        ("fc0", "valid"),
        ("fc0", "last_window_invalid_reason"),
        ("fc0", "fc0_valid_for_control"),
    }
    for key in transient_readiness_keys:
        assert key not in preflight.EXPECTED_STATUS
    assert preflight.EXPECTED_STATUS[("fc0", "fc0_fault")] == "false"

    transient = {
        ("fc0", "valid"): "false",
        ("fc0", "last_window_invalid_reason"): "no_samples",
        ("fc0", "fc0_valid_for_control"): "false",
        ("fc0", "fc0_fault"): "false",
    }
    assert preflight._mismatches(transient, preflight.READY_STATUS)

    ready = dict(preflight.READY_STATUS)
    assert preflight._mismatches(ready, preflight.READY_STATUS) == []


def test_fc0_qualification_wait_defaults_to_thirty_minutes() -> None:
    preflight = _load_preflight_module()
    signature = inspect.signature(preflight.verify_preflight)

    assert signature.parameters["response_timeout_s"].default == 20.0
    assert signature.parameters["qualification_timeout_s"].default == 1800.0
