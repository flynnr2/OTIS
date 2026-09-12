from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools.adaptive_hybrid_analyze import (
    _replay_control_preview_estimate_sources,
)
from host.otis_tools.contracts import CONTRACT_FIELDS


def _row(contract: str, **values: str) -> dict[str, str]:
    row = {field: "" for field in CONTRACT_FIELDS[contract]}
    row.update(values)
    return row


def _estimate(identifier: str = "est:selected:1") -> dict[str, str]:
    return _row(
        "estimates_v3",
        record_type="EST",
        schema_version="3",
        estimate_id=identifier,
        estimator_timestamp_ticks="123456",
        time_domain="rp2040_monotonic_us32",
    )


def _control(**changes: str) -> dict[str, str]:
    row = _row(
        "control_previews_v1",
        record_type="CTL",
        schema_version="1",
        decision_id="ctl:selected:1",
        decision_timestamp_ticks="123456",
        time_domain="rp2040_monotonic_us32",
        est_input_ref="est:selected:1",
    )
    row.update(changes)
    return row


def _wire(row: dict[str, str], contract: str) -> str:
    return ",".join(row[field] for field in CONTRACT_FIELDS[contract])


def _replay(
    tmp_path: Path,
    *,
    control: dict[str, str] | None = None,
    estimates: dict[str, dict[str, str]] | None = None,
    raw_rows: list[tuple[str, dict[str, str]]] | None = None,
) -> dict[str, object]:
    control_path = tmp_path / "csv/control_previews.csv"
    control_path.parent.mkdir(parents=True)
    controls = [] if control is None else [control]
    with control_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=CONTRACT_FIELDS["control_previews_v1"]
        )
        writer.writeheader()
        writer.writerows(controls)
    raw_path = tmp_path / "raw/serial.log"
    raw_path.parent.mkdir(parents=True)
    lines = []
    for contract, row in raw_rows or []:
        lines.append(_wire(row, contract))
    raw_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    manifest = SimpleNamespace(
        root=tmp_path,
        files=[
            {
                "contract": "control_previews_v1",
                "path": "csv/control_previews.csv",
            }
        ],
    )
    return _replay_control_preview_estimate_sources(
        manifest, {} if estimates is None else estimates
    )


def test_control_binds_to_earlier_exact_selected_estimate(tmp_path: Path) -> None:
    estimate = _estimate()
    control = _control()
    diagnostic = _estimate("est:diagnostic:1")

    result = _replay(
        tmp_path,
        control=control,
        estimates={estimate["estimate_id"]: estimate},
        raw_rows=[
            ("estimates_v3", diagnostic),
            ("estimates_v3", estimate),
            ("control_previews_v1", control),
        ],
    )

    assert result["exact"] is True
    assert result["error_count"] == 0
    assert result["joins"] == [
        {
            "decision_id": control["decision_id"],
            "estimate_id": estimate["estimate_id"],
            "timestamp_domain_exact": True,
            "raw_estimate_exact": True,
            "raw_control_exact": True,
            "publication_order_exact": True,
            "exact": True,
        }
    ]


def test_selected_estimate_without_control_is_legal(tmp_path: Path) -> None:
    estimate = _estimate()

    result = _replay(
        tmp_path,
        estimates={estimate["estimate_id"]: estimate},
        raw_rows=[("estimates_v3", estimate)],
    )

    assert result == {
        "exact": True,
        "applicability": "not_applicable_no_control_previews",
        "control_count": 0,
        "joins": [],
        "errors": [],
        "error_count": 0,
    }


@pytest.mark.parametrize(
    ("control_changes", "selected", "raw_order"),
    [
        ({"est_input_ref": "est:diagnostic:1"}, False, "normal"),
        ({"decision_timestamp_ticks": "123457"}, True, "normal"),
        ({"time_domain": "rp2040_monotonic_us64"}, True, "normal"),
        ({}, True, "reversed"),
        ({}, True, "missing_estimate"),
        ({}, True, "missing_control"),
        ({}, True, "duplicate_estimate"),
        ({}, True, "duplicate_control"),
    ],
)
def test_control_rejects_nonselected_identity_metadata_or_raw_order(
    tmp_path: Path,
    control_changes: dict[str, str],
    selected: bool,
    raw_order: str,
) -> None:
    estimate = _estimate()
    diagnostic = _estimate("est:diagnostic:1")
    control = _control(**control_changes)
    selected_estimates = {estimate["estimate_id"]: estimate} if selected else {}
    referenced = (
        diagnostic
        if control["est_input_ref"] == diagnostic["estimate_id"]
        else estimate
    )
    raw_rows = [
        ("estimates_v3", referenced),
        ("control_previews_v1", control),
    ]
    if raw_order == "reversed":
        raw_rows.reverse()
    elif raw_order == "missing_estimate":
        raw_rows = raw_rows[1:]
    elif raw_order == "missing_control":
        raw_rows = raw_rows[:1]
    elif raw_order == "duplicate_estimate":
        raw_rows.insert(1, raw_rows[0])
    elif raw_order == "duplicate_control":
        raw_rows.append(raw_rows[-1])

    result = _replay(
        tmp_path,
        control=control,
        estimates=selected_estimates,
        raw_rows=raw_rows,
    )

    assert result["exact"] is False
    assert result["error_count"] == 1
    assert result["joins"][0]["exact"] is False


def test_unrelated_malformed_diagnostic_does_not_enter_control_join(
    tmp_path: Path,
) -> None:
    estimate = _estimate()
    control = _control()
    result = _replay(
        tmp_path,
        control=control,
        estimates={estimate["estimate_id"]: estimate},
        raw_rows=[
            ("estimates_v3", estimate),
            ("control_previews_v1", control),
        ],
    )
    raw_path = tmp_path / "raw/serial.log"
    raw_path.write_bytes(b"EST,broken,diagnostic\n" + raw_path.read_bytes())

    result = _replay_control_preview_estimate_sources(
        SimpleNamespace(
            root=tmp_path,
            files=[
                {
                    "contract": "control_previews_v1",
                    "path": "csv/control_previews.csv",
                }
            ],
        ),
        {estimate["estimate_id"]: estimate},
    )

    assert result["exact"] is True
    assert result["error_count"] == 0


def test_control_join_bounds_reported_errors(tmp_path: Path) -> None:
    control_path = tmp_path / "csv/control_previews.csv"
    control_path.parent.mkdir(parents=True)
    controls = [
        _control(
            decision_id=f"ctl:selected:{index}",
            est_input_ref=f"est:selected:{index}",
        )
        for index in range(25)
    ]
    with control_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=CONTRACT_FIELDS["control_previews_v1"]
        )
        writer.writeheader()
        writer.writerows(controls)
    raw_path = tmp_path / "raw/serial.log"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"")

    result = _replay_control_preview_estimate_sources(
        SimpleNamespace(
            root=tmp_path,
            files=[
                {
                    "contract": "control_previews_v1",
                    "path": "csv/control_previews.csv",
                }
            ],
        ),
        {},
    )

    assert result["exact"] is False
    assert result["error_count"] == 25
    assert len(result["errors"]) == 20
