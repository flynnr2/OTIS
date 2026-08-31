from host.otis_tools import cx323_successor_offline_study as study


def _observation(*, code: int = 43085, epoch: int = 13, opening: int = 0,
                 closing: int = 600, counts: int = -1, phase: int = -4,
                 cadence: bool = True) -> study.Observation:
    return study.Observation(
        study.Identity("fixture", code, epoch, "phase-1", True, "selected"),
        opening,
        closing,
        counts,
        phase,
        cadence_eligible=cadence,
    )


def test_frozen_contract_and_attempt4_bindings_are_exact() -> None:
    contract = study.load_contract()
    v1_contract = study.load_v1_contract()
    bound = study.validate_bound_sources(v1_contract)

    assert contract["contract_sha256"] == study.EXPECTED_CONTRACT_SHA256
    assert contract["base_contract"]["contract_sha256"] == study.EXPECTED_V1_CONTRACT_SHA256
    assert v1_contract["contract_sha256"] == study.EXPECTED_V1_CONTRACT_SHA256
    assert bound["bound_file_count"] == 11
    assert bound["run_id"] == "hybrid_72h_attempt4"


def test_request_order_persistence_cadence_cap_and_debt_commit() -> None:
    initial = study.State()
    first = study.evaluate_maintenance(initial, _observation(cadence=False), tagged_debt=True)
    second = study.evaluate_maintenance(first.state, _observation(opening=600, closing=1200), tagged_debt=True)

    assert first.reason == "cadence_hold_no_accrual"
    assert first.state.count == 1
    assert second.delta == 5
    assert second.cap == 5
    assert second.state.debt.total == 0  # request is not a debt commit
    assert second.state.request_pending is True

    committed = study.confirm_application(
        second, applied_code=43090, dac_epoch=14,
        first_consumer_exact=True, tagged_debt=True,
    )
    assert committed.debt.total == 341_671_780_415
    assert isinstance(committed.debt.fll, int)
    assert isinstance(committed.debt.pll, int)
    assert committed.debt.fll + committed.debt.pll == committed.debt.total
    assert committed.count == 0
    assert committed.request_pending is False
    assert committed.response_pending is True
    completed = study.complete_response(committed, fresh_exact_response=True)
    assert completed.response_pending is False
    assert completed.debt == committed.debt


def test_holds_and_unowned_epoch_transition_preserve_or_fail_static() -> None:
    debt = study.Debt(250_000_000_000, 125_000_000_000)
    held = study.enter_metadata_hold(study.State(debt=debt))
    frozen = study.evaluate_maintenance(held, _observation(), tagged_debt=True)

    assert frozen.reason == "metadata_hold_frozen"
    assert frozen.state.debt == debt

    first = study.evaluate_maintenance(study.State(), _observation(), tagged_debt=True)
    unknown = study.evaluate_maintenance(
        first.state, _observation(code=43086, opening=600, closing=1200), tagged_debt=True
    )
    assert unknown.reason == "actuator_provenance_fail_static"
    assert unknown.state.fail_static is True


def test_shared_endpoint_advances_while_overlap_and_gap_are_distinct() -> None:
    first = study.evaluate_maintenance(study.State(), _observation(), tagged_debt=True)
    contiguous = study.evaluate_maintenance(
        first.state, _observation(opening=600, closing=1200), tagged_debt=True
    )
    overlap = study.evaluate_maintenance(
        first.state, _observation(opening=599, closing=1199), tagged_debt=True
    )
    gap = study.evaluate_maintenance(
        first.state, _observation(opening=601, closing=1201), tagged_debt=True
    )

    assert contiguous.delta == 5
    assert contiguous.state.request_pending is True
    assert overlap.reason == "source_overlap_hold"
    assert overlap.state == first.state
    assert gap.reason == "source_gap_restart"
    assert gap.state.count == 1
    assert gap.state.debt == study.Debt()


def test_v2_debt_transition_table_preserves_holds_and_separates_rejection() -> None:
    debt = study.Debt(200_000_000_000, 100_000_000_000)
    settling = study.evaluate_maintenance(
        study.State(debt=debt),
        study.Observation(
            _observation().identity, 0, 600, -1, -4, settled=False
        ),
        tagged_debt=True,
    )
    reference = study.evaluate_maintenance(
        study.State(debt=debt),
        study.Observation(
            _observation().identity, 0, 600, -1, -4, qualified=False
        ),
        tagged_debt=True,
    )
    zero = study.evaluate_maintenance(
        study.State(debt=debt),
        _observation(counts=0, phase=0),
        tagged_debt=True,
    )

    assert settling.state.debt == debt
    assert reference.state.debt == debt
    assert zero.state.debt == study.Debt()
    assert study.new_policy_activation(study.State(debt=debt)).debt == study.Debt()

    first = study.evaluate_maintenance(study.State(), _observation(), tagged_debt=True)
    request = study.evaluate_maintenance(
        first.state, _observation(opening=600, closing=1200), tagged_debt=True
    )
    rejected = study.reject_or_expire_request(request.state)
    incomplete = study.confirm_application(
        request, applied_code=43090, dac_epoch=14,
        first_consumer_exact=False, tagged_debt=True,
    )

    assert rejected.request_pending is False
    assert rejected.response_pending is False
    assert rejected.debt == request.state.debt
    assert incomplete.fail_static is True


def test_bounded_debt_fixture_and_full_report_select_tagged_non_effectively() -> None:
    fixture = study.bounded_debt_residual_fixture()
    report = study.create_report()

    assert fixture["pass"] is True
    assert fixture["tagged_debt_final_delta_codes"] == 6
    assert fixture["tagged_debt_distance_picocodes"] < fixture["no_debt_distance_picocodes"]
    assert report["exact_physical_prefix"]["last_decision_sequence"] == 27
    assert report["exact_physical_prefix"]["application_count"] == 8
    assert report["contract_id"] == study.CONTRACT_ID
    assert report["superseded_v1_execution"]["v1_selection_may_not_be_used_for_promotion"] is True
    assert all(item["pass"] for item in report["fixed_point_mandatory_checks"])
    assert all(
        item["same_frontier_diagnostic"]["first_decision"]["provenance"]
        == study.COUNTERFACTUAL
        for item in report["candidates"]
    )
    assert report["selection"] == {
        "selected_candidate_id": study.TAGGED_DEBT_ID,
        "terminal": "cx323_tagged_debt_candidate_selected_non_effective",
        "effective_or_promoted": False,
        "physical_authority_granted": False,
    }
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    assert report["report_sha256"] == study.canonical_sha256(unsigned)
