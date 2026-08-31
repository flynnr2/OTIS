from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


CANONICAL_MANIFEST = "run_manifest.json"
CAPTURE_IN_PROGRESS_FLAG = "capture_in_progress.flag"
COMPLETE_MARKER = "COMPLETE"
CURRENT_EVIDENCE_EPOCH = "CX319_EVIDENCE_EPOCH_1"
SUSTAINED_HYBRID_EVIDENCE_EPOCH = "OTIS_SUSTAINED_HYBRID_EVIDENCE_EPOCH_1"
SUSTAINED_HYBRID_STAGE = "OTIS_SUSTAINED_HYBRID_REGULATION_LIVE"
SUSTAINED_HYBRID_PROFILE_ID = "otis_sustained_hybrid_regulation_v1"
CX322_D9_D6_INTEGRATION_EVIDENCE_EPOCH = (
    "OTIS_CX322_D9_D6_INTEGRATION_EVIDENCE_EPOCH_1"
)
CX322_D9_D6_INTEGRATION_STAGE = (
    "OTIS_CX322_D9_D6_INTEGRATION_ENGINEERING_LIVE"
)
CX322_D9_D6_INTEGRATION_PROFILE_ID = (
    "cx322_d9_d6_integration_engineering"
)
CX322_D9_D6_72H_EVIDENCE_EPOCH = (
    "OTIS_CX322_D9_D6_72H_EVIDENCE_EPOCH_1"
)
CX322_D9_D6_72H_STAGE = (
    "OTIS_CX322_D9_D6_72H_SUSTAINED_ENGINEERING_LIVE"
)
CX322_D9_D6_72H_PROFILE_ID = "cx322_d9_d6_72h_sustained_engineering"
CX322_D9_D6_72H_PROGRAMME_ID = (
    "OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_V1"
)
CX323_D9_D6_72H_EVIDENCE_EPOCH = (
    "OTIS_CX323_D9_D6_72H_EVIDENCE_EPOCH_1"
)
CX323_D9_D6_72H_STAGE = "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_LIVE"
CX323_D9_D6_72H_PROFILE_ID = "cx323_d9_d6_72h_adaptive_hybrid"
CX323_D9_D6_72H_PROGRAMME_ID = "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_V1"
GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH = "OTIS_GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH_1"
GNSS_BAUD_ENVELOPE_STAGE = "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_LIVE"
GNSS_BAUD_ENVELOPE_PROFILE_ID = "otis_gnss_baud_envelope_characterization_v1"
GNSS_BAUD_CONTINUATION_EVIDENCE_EPOCH = (
    "OTIS_GNSS_BAUD_ENVELOPE_CONTINUATION_EVIDENCE_EPOCH_1"
)
GNSS_BAUD_CONTINUATION_STAGE = (
    "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_CONTINUATION_LIVE"
)
GNSS_BAUD_CONTINUATION_PROFILE_ID = (
    "otis_gnss_baud_envelope_characterization_continuation_v1"
)
GNSS_BAUD_RESUME_EVIDENCE_EPOCH = (
    "OTIS_GNSS_BAUD_ENVELOPE_RESUME_EVIDENCE_EPOCH_1"
)
GNSS_BAUD_RESUME_STAGE = "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_RESUME_LIVE"
GNSS_BAUD_RESUME_PROFILE_ID = "otis_gnss_baud_envelope_characterization_resume_v1"
D9_D6_FREQUENCY_ONLY_ENDURANCE_EVIDENCE_EPOCH = (
    "OTIS_D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_EPOCH_1"
)
D9_D6_FREQUENCY_ONLY_ENDURANCE_STAGE = (
    "OTIS_D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_LIVE"
)
D9_D6_FREQUENCY_ONLY_ENDURANCE_PROFILE_ID = "d9_d6_frequency_only_lower"
CURRENT_PACKAGE_PROFILE_IDENTITIES = frozenset(
    {
        "cx319_tight_lower",
        "cx319_tight_upper",
        "cx319_q2_inhibited_transaction",
        "cx319_range_map_part_a",
        "cx319_range_part_b_lower",
        "cx319_range_part_b_upper",
        "cx319_range_part_b_upper_completion",
        "cx320_active_hybrid",
        "cx321_active_hybrid",
        "cx322_direct_hybrid",
        "cx322_d9_d6_integration_engineering",
        # Current non-actuating forwarded-output readiness packages.  These
        # profiles have no DAC/FLL/hybrid authority and are admitted solely so
        # their capture/analyzer/seal evidence can use the current lifecycle.
        "d9_disabled_no_control_baseline",
        "d9_forwarded_output_no_control",
        "d9_d6_forwarded_output_no_control",
        "d9_d6_frequency_only_lower",
    }
)
ARCHIVAL_CHECKOUT_GUIDANCE = (
    "unsupported historical OTIS package; use its recorded Git revision or "
    "an archival checkout to reproduce it"
)


@dataclass(frozen=True)
class RunManifest:
    root: Path
    path: Path
    data: dict

    @property
    def run_id(self) -> str:
        return str(self.data["run_id"])

    @property
    def files(self) -> list[dict]:
        return list(self.data.get("files", []))

    @property
    def is_template(self) -> bool:
        return bool(self.data.get("template", False))

    @property
    def stage(self) -> str | None:
        stage = self.data.get("stage")
        return str(stage) if stage not in (None, "") else None

    @property
    def capture_mode(self) -> str | None:
        mode = self.data.get("capture_mode")
        if mode not in (None, ""):
            return str(mode)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("capture_mode"):
            return str(firmware["capture_mode"])
        return None

    @property
    def board(self) -> str | None:
        board = self.data.get("board")
        if board not in (None, ""):
            return str(board)
        hardware = self.data.get("hardware")
        if isinstance(hardware, dict) and hardware.get("capture_board"):
            return str(hardware["capture_board"])
        return None

    @property
    def firmware_name(self) -> str | None:
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("name"):
            return str(firmware["name"])
        name = self.data.get("firmware_name")
        return str(name) if name not in (None, "") else None

    @property
    def firmware_version(self) -> str | None:
        version = self.data.get("firmware_version")
        if version not in (None, ""):
            return str(version)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("version"):
            return str(firmware["version"])
        return None

    @property
    def firmware_git_commit(self) -> str | None:
        commit = self.data.get("firmware_git_commit")
        if commit not in (None, ""):
            return str(commit)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("git_commit"):
            return str(firmware["git_commit"])
        return None

    @property
    def host_tool_version(self) -> str | None:
        version = self.data.get("host_tool_version")
        if version not in (None, ""):
            return str(version)
        host = self.data.get("host")
        if isinstance(host, dict) and host.get("version"):
            return str(host["version"])
        return None

    @property
    def host_git_commit(self) -> str | None:
        commit = self.data.get("host_git_commit")
        if commit not in (None, ""):
            return str(commit)
        host = self.data.get("host")
        if isinstance(host, dict) and host.get("git_commit"):
            return str(host["git_commit"])
        return None

    @property
    def expected_artifacts(self) -> list[str]:
        expected = self.data.get("expected_artifacts")
        if isinstance(expected, list):
            return [str(item) for item in expected]
        return [str(file_entry.get("path", "")) for file_entry in self.files if file_entry.get("path")]

    @property
    def known_limitations(self) -> list[str]:
        limitations = self.data.get("known_limitations")
        if isinstance(limitations, list):
            return [str(item) for item in limitations]
        return []

    @property
    def known_channels(self) -> frozenset[int]:
        channels: set[int] = set()
        for channel in self.data.get("channels", []):
            if "channel_id" in channel:
                channels.add(int(channel["channel_id"]))
        return frozenset(channels)

    @property
    def known_domains(self) -> frozenset[str]:
        return frozenset(str(domain["name"]) for domain in self.data.get("domains", []) if "name" in domain)


@dataclass(frozen=True)
class RunState:
    capture_in_progress: bool
    complete: bool


def find_manifest_path(run_dir: Path) -> Path | None:
    path = run_dir / CANONICAL_MANIFEST
    return path if path.exists() else None


def _require_current_epoch(data: dict) -> None:
    stage = str(data.get("stage", ""))
    run_id = str(data.get("run_id", ""))
    gnss_profile_by_stage = {
        GNSS_BAUD_ENVELOPE_STAGE: (
            GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH,
            GNSS_BAUD_ENVELOPE_PROFILE_ID,
        ),
        GNSS_BAUD_CONTINUATION_STAGE: (
            GNSS_BAUD_CONTINUATION_EVIDENCE_EPOCH,
            GNSS_BAUD_CONTINUATION_PROFILE_ID,
        ),
        GNSS_BAUD_RESUME_STAGE: (
            GNSS_BAUD_RESUME_EVIDENCE_EPOCH,
            GNSS_BAUD_RESUME_PROFILE_ID,
        ),
    }
    if stage in gnss_profile_by_stage:
        epoch, profile_id = gnss_profile_by_stage[stage]
        programme = data.get("gnss_baud_envelope")
        if (
            data.get("compatibility_floor") == epoch
            and isinstance(programme, dict)
            and programme.get("profile_id") == profile_id
            and programme.get("programme_id")
            == "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1"
        ):
            return
        raise ValueError(
            f"manifest does not satisfy {epoch}; {ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage == SUSTAINED_HYBRID_STAGE:
        programme = data.get("sustained_hybrid")
        if (
            data.get("compatibility_floor") == SUSTAINED_HYBRID_EVIDENCE_EPOCH
            and isinstance(programme, dict)
            and programme.get("profile_id") == SUSTAINED_HYBRID_PROFILE_ID
        ):
            return
        raise ValueError(
            f"manifest does not satisfy {SUSTAINED_HYBRID_EVIDENCE_EPOCH}; "
            f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage == CX322_D9_D6_INTEGRATION_STAGE:
        programme = data.get("cx322_d9_d6_integration")
        if (
            data.get("compatibility_floor")
            == CX322_D9_D6_INTEGRATION_EVIDENCE_EPOCH
            and isinstance(programme, dict)
            and programme.get("profile_id")
            == CX322_D9_D6_INTEGRATION_PROFILE_ID
        ):
            return
        raise ValueError(
            "manifest does not satisfy "
            f"{CX322_D9_D6_INTEGRATION_EVIDENCE_EPOCH}; "
            f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage == CX322_D9_D6_72H_STAGE:
        programme = data.get("cx322_d9_d6_72h")
        if (
            data.get("compatibility_floor") == CX322_D9_D6_72H_EVIDENCE_EPOCH
            and data.get("programme_id") == CX322_D9_D6_72H_PROGRAMME_ID
            and isinstance(programme, dict)
            and programme.get("profile_id") == CX322_D9_D6_72H_PROFILE_ID
        ):
            return
        raise ValueError(
            "manifest does not satisfy "
            f"{CX322_D9_D6_72H_EVIDENCE_EPOCH}; "
            f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage == CX323_D9_D6_72H_STAGE:
        programme = data.get("cx323_d9_d6_72h")
        if (
            data.get("compatibility_floor") == CX323_D9_D6_72H_EVIDENCE_EPOCH
            and data.get("programme_id") == CX323_D9_D6_72H_PROGRAMME_ID
            and isinstance(programme, dict)
            and programme.get("profile_id") == CX323_D9_D6_72H_PROFILE_ID
        ):
            return
        raise ValueError(
            "manifest does not satisfy "
            f"{CX323_D9_D6_72H_EVIDENCE_EPOCH}; "
            f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage == D9_D6_FREQUENCY_ONLY_ENDURANCE_STAGE:
        programme = data.get("frequency_only_engineering")
        if (
            data.get("compatibility_floor")
            == D9_D6_FREQUENCY_ONLY_ENDURANCE_EVIDENCE_EPOCH
            and isinstance(programme, dict)
            and programme.get("profile_id")
            == D9_D6_FREQUENCY_ONLY_ENDURANCE_PROFILE_ID
            and programme.get("contract_id")
            == "OTIS_D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_V1"
            and programme.get("digital_endurance_only") is True
        ):
            return
        raise ValueError(
            "manifest does not satisfy "
            f"{D9_D6_FREQUENCY_ONLY_ENDURANCE_EVIDENCE_EPOCH}; "
            f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
        )
    if stage.startswith("CX322_"):
        programme = data.get("cx322")
    elif stage.startswith("CX321_"):
        programme = data.get("cx321")
    elif stage.startswith("CX320_"):
        programme = data.get("cx320")
    else:
        programme = data.get("cx319")
    current_profile = (
        isinstance(programme, dict)
        and programme.get("profile_id") in CURRENT_PACKAGE_PROFILE_IDENTITIES
    )
    if stage.startswith(("CX319_", "CX320_", "CX321_", "CX322_")) and current_profile:
        return
    if (
        stage == "CX318_STAGE5_TRANSITION_SPOOL"
        and run_id.endswith("owner_handoff_transition")
    ):
        return
    legacy_keys = {
        "bringup_mode",
        "phase4_discipline_replay",
        "phase5_pps_backend_qualification",
    }
    if data.get("h_phase") in {"H0", "H1"} or legacy_keys.intersection(data):
        raise ValueError(ARCHIVAL_CHECKOUT_GUIDANCE)
    if stage in {"SW1", "H0", "H1"} or stage.startswith(("CX317_", "PHASE4_", "PHASE5_")):
        raise ValueError(ARCHIVAL_CHECKOUT_GUIDANCE)
    if stage.startswith("CX318_"):
        raise ValueError(ARCHIVAL_CHECKOUT_GUIDANCE)
    if data.get("compatibility_floor") == CURRENT_EVIDENCE_EPOCH and current_profile:
        return
    raise ValueError(
        f"manifest does not satisfy {CURRENT_EVIDENCE_EPOCH}; "
        f"{ARCHIVAL_CHECKOUT_GUIDANCE}"
    )


def inspect_run_state(run_dir: Path) -> RunState:
    return RunState(
        capture_in_progress=(run_dir / CAPTURE_IN_PROGRESS_FLAG).exists(),
        complete=(run_dir / COMPLETE_MARKER).exists(),
    )


def load_manifest(run_dir: Path) -> RunManifest:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is None:
        legacy_path = run_dir / "manifest.json"
        if legacy_path.exists():
            raise ValueError(
                f"legacy manifest.json is not supported; {ARCHIVAL_CHECKOUT_GUIDANCE}"
            )
        raise FileNotFoundError(
            f"missing canonical {CANONICAL_MANIFEST} in {run_dir}"
        )
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema_version: {data.get('schema_version')!r}")
    if not data.get("run_id"):
        raise ValueError("manifest missing run_id")
    if not isinstance(data.get("files"), list) or not data["files"]:
        raise ValueError("manifest must list at least one data file")

    _require_current_epoch(data)
    return RunManifest(root=run_dir, path=manifest_path, data=data)
