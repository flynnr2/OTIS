"""Exact, non-authorizing replay of the current tight-deadband policy."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    CsvValidationContext,
    TIGHT_DEADBAND_POLICY_SHA256,
    validate_csv,
)
from .integer_count_tight_deadband import TightHystereticDeadband
from .run_paths import TIGHT_DEADBAND_DECISIONS_CSV


CONTRACT = "tight_deadband_decisions_v1"


@dataclass(frozen=True)
class TightDeadbandReplayResult:
    """The full evidence result; a mismatch is evidence, never an authority."""

    source_path: Path
    row_count: int
    comparisons: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]

    @property
    def exact(self) -> bool:
        return not self.errors

    @property
    def ok(self) -> bool:
        return self.exact

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_path"] = str(self.source_path)
        result["exact"] = self.exact
        result["ok"] = self.ok
        return result


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _expected_fields(
    row: dict[str, str],
    deadband: TightHystereticDeadband,
    *,
    policy_sha256: str,
) -> dict[str, str]:
    counts = int(row["integer_edge_error_counts"], 10)
    decision = deadband.observe(
        accumulated_edge_error_counts=counts,
        fresh=True,
        session=int(row["capture_session"], 10),
        dac_epoch=int(row["dac_epoch"], 10),
    )
    absolute = abs(counts)
    return {
        "policy_id": decision.policy_id,
        "policy_sha256": policy_sha256,
        "absolute_edge_error_counts": str(absolute),
        "state_before": decision.state_before,
        "state_after": decision.state_after,
        "entry_counter": str(decision.entry_pending_count),
        "release_counter": str(decision.release_pending_count),
        "transition": _bool_text(decision.state_before != decision.state_after),
        "frequency_controller_eligible": _bool_text(
            decision.frequency_controller_eligible
        ),
        "requalified": _bool_text(decision.requalified),
        "requalification_reason": decision.requalification_reason or "",
        "historical_v2_inside": _bool_text(absolute <= 3),
        "symmetric_two_count_inside": _bool_text(absolute <= 2),
        "actionable": "false",
        "actuation_authorized": "false",
        "authorization_consumed": "false",
        "reason_codes": decision.reason,
    }


def replay_tight_deadband_chain(
    paths: list[Path],
    *,
    policy_sha256: str = TIGHT_DEADBAND_POLICY_SHA256,
) -> TightDeadbandReplayResult:
    """Replay consecutive logical segments through one deadband instance.

    Same-owner Stage 5 promotion rotates files, not firmware state.  Replaying
    each file from a fresh deadband could therefore reject the first row after
    a logical rotation or, worse, conceal a bad transition.  This entry point
    validates each file independently while preserving the state machine over
    the complete ordered chain.
    """

    if not paths:
        raise ValueError("tight-deadband replay chain is empty")
    resolved = [Path(path).resolve() for path in paths]
    errors: list[str] = []
    comparisons: list[dict[str, Any]] = []
    row_count = 0
    deadband = TightHystereticDeadband()
    for path in resolved:
        validation = validate_csv(
            path,
            CsvValidationContext(
                contract=CONTRACT,
                known_channels=frozenset(),
                known_domains=frozenset(),
                allow_rp2040_timer0_wrap=True,
                tight_deadband_policy_sha256=policy_sha256,
            ),
        )
        for error in validation.errors:
            errors.append(f"{path}: {error}")
        if validation.errors:
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for local_row, row in enumerate(reader, start=1):
                row_count += 1
                expected = _expected_fields(
                    row, deadband, policy_sha256=policy_sha256
                )
                mismatches = {
                    field_name: {
                        "observed": row.get(field_name, ""),
                        "expected": value,
                    }
                    for field_name, value in expected.items()
                    if row.get(field_name, "") != value
                }
                comparisons.append(
                    {
                        "source_path": str(path),
                        "source_row": local_row,
                        "row": row_count,
                        "decision_sequence": row.get("decision_sequence", ""),
                        "pass": not mismatches,
                        "mismatches": mismatches,
                    }
                )
                for field_name, values in mismatches.items():
                    errors.append(
                        f"{path} row {local_row}: {field_name} replay mismatch; "
                        f"observed={values['observed']!r}, "
                        f"expected={values['expected']!r}"
                    )
    return TightDeadbandReplayResult(
        source_path=resolved[-1],
        row_count=row_count,
        comparisons=tuple(comparisons),
        errors=tuple(errors),
    )


def replay_tight_deadband(
    path: Path,
    *,
    policy_sha256: str = TIGHT_DEADBAND_POLICY_SHA256,
) -> TightDeadbandReplayResult:
    """Replay every captured TDB row and require exact active/shadow parity.

    The wire record is only emitted for fresh authoritative 600-second integer
    count observations.  Therefore replay intentionally supplies ``fresh=True``
    and treats the captured session and DAC epoch as the identity boundary.
    """

    return replay_tight_deadband_chain(
        [path], policy_sha256=policy_sha256
    )


def replay_run(run_dir: Path) -> TightDeadbandReplayResult:
    """Replay the canonical captured TDB product in a run directory."""

    return replay_tight_deadband(run_dir / "csv" / TIGHT_DEADBAND_DECISIONS_CSV)


def validate_replay(path: Path) -> TightDeadbandReplayResult:
    """Compatibility-friendly name for callers using this as a validator."""

    return replay_tight_deadband(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exact replay validator for tight-deadband evidence."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="TDB CSV product to replay.")
    source.add_argument("--run-dir", type=Path, help="Run directory containing the TDB CSV product.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = replay_run(args.run_dir) if args.run_dir is not None else replay_tight_deadband(args.csv)
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    raise SystemExit(0 if result.exact else 1)


if __name__ == "__main__":
    main()
