from __future__ import annotations

from pathlib import Path

import pytest

from tools.firmware_matrix import (
    D6_MONITOR_BINARY_MARKERS,
    D9_D6_BINARY_MARKERS,
    D9_D6_FORBIDDEN_BINARY_MARKERS,
    DEFAULT_MATRIX,
    MatrixError,
    _d9_d6_binary_contract,
    load_matrix,
)


def _profile(profile_id: str) -> dict:
    return next(
        profile
        for profile in load_matrix(DEFAULT_MATRIX)["profiles"]
        if profile["id"] == profile_id
    )


def _write_binary(path: Path, *markers: bytes) -> None:
    (path / "candidate.bin").write_bytes(
        b"synthetic flashable BIN\x00" + b"\x00".join(markers)
    )


def test_d9_d6_selected_binary_binds_exact_contract_and_cpu_sidecar(
    tmp_path: Path,
) -> None:
    _write_binary(
        tmp_path,
        *D9_D6_BINARY_MARKERS.values(),
        *D6_MONITOR_BINARY_MARKERS.values(),
    )

    result = _d9_d6_binary_contract(
        _profile("d9_d6_forwarded_output_no_control"), tmp_path
    )

    assert result["status"] == "verified"
    assert result["readiness_contract"] == {
        "path": (
            "docs/60_EXPERIMENTS/"
            "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/"
            "d9_d6_readiness_contract_v1.json"
        ),
        "contract_id": "OTIS_D9_D6_READINESS_CONTRACT_V1",
        "contract_semantic_sha256": (
            "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d"
        ),
    }
    assert result["topology_contract"] == {
        **result["readiness_contract"],
        "binding_scope": (
            "fixed_D8_GPIN0_to_D9_GPOUT0_and_D6_zero_authority_sidecar"
        ),
    }
    assert result["authority_scope"] == "no_control_readiness"
    assert all(result["required_markers"]["d9_output"].values())
    assert all(result["required_markers"]["d6_monitor"].values())
    assert result["selectors"]["OTIS_ENABLE_D9_D6_READINESS_PROFILE"] == "1"
    assert result["selectors"]["all_control_write_selectors_disabled"] is True
    assert result["selectors"]["d9_has_control_authority"] is False
    assert result["selectors"]["d6_has_control_authority"] is False


def test_d9_binary_rejects_missing_fixed_output_marker(tmp_path: Path) -> None:
    missing_name = "readback"
    _write_binary(
        tmp_path,
        *(
            marker
            for name, marker in D9_D6_BINARY_MARKERS.items()
            if name != missing_name
        ),
    )

    with pytest.raises(MatrixError, match=r"fixed-output markers: \['readback'\]"):
        _d9_d6_binary_contract(_profile("d9_forwarded_output_no_control"), tmp_path)


def test_d6_selected_binary_rejects_missing_cpu_snapshot_marker(tmp_path: Path) -> None:
    _write_binary(
        tmp_path,
        *D9_D6_BINARY_MARKERS.values(),
        *(
            marker
            for name, marker in D6_MONITOR_BINARY_MARKERS.items()
            if name != "cpu_snapshot_backend"
        ),
    )

    with pytest.raises(
        MatrixError, match=r"diagnostic-monitor markers: \['cpu_snapshot_backend'\]"
    ):
        _d9_d6_binary_contract(
            _profile("d9_d6_forwarded_output_no_control"), tmp_path
        )


def test_d9_binary_rejects_future_runtime_or_fractional_selection_surface(
    tmp_path: Path,
) -> None:
    _write_binary(
        tmp_path,
        *D9_D6_BINARY_MARKERS.values(),
        D9_D6_FORBIDDEN_BINARY_MARKERS["nonzero_fractional_divider"],
    )

    with pytest.raises(MatrixError, match="runtime/fractional selection markers"):
        _d9_d6_binary_contract(_profile("d9_forwarded_output_no_control"), tmp_path)


def test_non_d9_profile_explicitly_reports_disabled_binary_contract(
    tmp_path: Path,
) -> None:
    _write_binary(tmp_path, b"unrelated")

    result = _d9_d6_binary_contract(_profile("cx319_tight_lower"), tmp_path)

    assert result["status"] == "disabled_profile"
    assert result["output_selection"] == "disabled"
    assert result["monitor_selection"] == "disabled"
    assert result["readiness_contract"] is None
    assert result["topology_contract"] is None


def test_d9_binary_contract_ignores_non_flashable_elf_debug_markers(
    tmp_path: Path,
) -> None:
    _write_binary(tmp_path, *D9_D6_BINARY_MARKERS.values())
    (tmp_path / "candidate.elf").write_bytes(
        b"debug-only\x00"
        + D9_D6_FORBIDDEN_BINARY_MARKERS["nonzero_fractional_divider"]
    )

    result = _d9_d6_binary_contract(
        _profile("d9_forwarded_output_no_control"), tmp_path
    )

    assert result["status"] == "verified"
    assert not any(result["forbidden_markers_present"].values())


def test_integrated_hybrid_binary_binds_topology_without_false_readiness(
    tmp_path: Path,
) -> None:
    _write_binary(
        tmp_path,
        *D9_D6_BINARY_MARKERS.values(),
        *D6_MONITOR_BINARY_MARKERS.values(),
    )

    result = _d9_d6_binary_contract(
        _profile("cx322_d9_d6_integration_engineering"), tmp_path
    )

    assert result["status"] == "verified"
    assert result["readiness_contract"] is None
    assert result["topology_contract"]["contract_id"] == (
        "OTIS_D9_D6_READINESS_CONTRACT_V1"
    )
    assert result["authority_scope"] == (
        "D9_D6_topology_only_controller_authority_is_separate"
    )
    assert result["selectors"]["all_control_write_selectors_disabled"] is False
    assert result["selectors"]["d9_has_control_authority"] is False
    assert result["selectors"]["d6_has_control_authority"] is False
