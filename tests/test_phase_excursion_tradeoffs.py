"""Finite model regressions; these tests confer no physical authority."""

import json

from tools.audit_large_steering_steps import audit
from tools.compare_phase_excursion_tradeoffs import CONTRACT, cases, run


def test_frozen_matrix_covers_signs_boundaries_and_glitches():
    contract = json.loads(CONTRACT.read_bytes())
    matrix = cases(contract)
    assert len(matrix) == 3060
    assert {r["family"] for r in matrix} == set(range(7))
    assert {r["position"] for r in matrix} == {1, 150, 300, 450, 600}
    assert {r["fraction"] for r in matrix} == {0, 0.25, 0.5, 0.75}
    assert min(r["pulse"] for r in matrix) == -8
    assert max(r["pulse"] for r in matrix) == 8
    assert contract["authority"] == "offline_only_no_instrument_or_baseline_authority"


def test_retained_large_steps_have_different_source_shapes(tmp_path):
    result = audit(tmp_path / "audit")
    r = {x["dac_epoch"]: x for x in result["applications"]}
    assert len(r) == 7
    assert r[36]["multicycle_spans"] == [(13, 3)]
    assert r[305]["multicycle_spans"] == [(202, 4)]
    assert not r[126]["multicycle_spans"] and r[126]["nonzero_spans"] == 29
    projected = lambda epoch, name: next(
        x for x in r[epoch]["projections"] if x["candidate"] == name
    )
    assert projected(36, "single_span_FLL_separation")["delta_codes"] == -1
    assert projected(305, "single_span_FLL_separation")["delta_codes"] == -1
    assert projected(36, "single_span_one_window_confirmation")["confirmation_pending"]
    assert projected(126, "single_span_one_window_confirmation")["delta_codes"] == 15
    assert not r[266]["projections"]  # no invented maintenance persistence state


def test_native_smoke_model_includes_application_cadence_and_count_quantization(
    tmp_path,
):
    result = run(tmp_path / "model", quick=True)
    assert result["model_rows"] == 12
    groups = {(r["family"], r["candidate"]): r for r in result["summary"]}
    assert groups["localized_reference_phase", "baseline"]["maximum_step"]["max"] == 20
    assert (
        groups["localized_reference_phase", "single_span_one_window_confirmation"][
            "maximum_step"
        ]["max"]
        == 1
    )
    assert (
        groups["frequency_step", "single_span_FLL_separation"][
            "additional_first_correct_application_delay_s"
        ]["max"]
        == 0
    )
    assert (
        groups["frequency_step", "segmented_with_local_confirmation_fallback"][
            "integrated_error_ratio_to_baseline"
        ]["mean"]
        == 1
    )
