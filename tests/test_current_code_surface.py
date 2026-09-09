from __future__ import annotations

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CURRENT_ROOTS = ("firmware", "host", "tools", "profiles", "schemas", "tests")
EXECUTABLE_SUFFIXES = {
    ".c",
    ".cc",
    ".cmake",
    ".cpp",
    ".cxx",
    ".h",
    ".ino",
    ".json",
    ".pio",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}


def _current_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        path = Path(raw.decode("utf-8"))
        if (
            path.parts
            and path.parts[0] in CURRENT_ROOTS
            and path.suffix in EXECUTABLE_SUFFIXES
            and (ROOT / path).is_file()
        ):
            paths.append(path)
    return sorted(set(paths))


def test_retired_campaign_identities_are_absent_from_current_code() -> None:
    # Every numbered identity except the physical oscillator is retired.  Keep
    # the expression assembled so the guard does not have to exempt its source.
    numbered = re.compile("cx" + r"(?P<number>[0-9]+)", re.IGNORECASE)
    violations: list[str] = []
    for path in _current_files():
        relative = path.as_posix()
        path_matches = [
            match.group(0)
            for match in numbered.finditer(relative)
            if int(match.group("number")) != 317
        ]
        if path_matches:
            violations.append(f"path:{relative}")
            continue
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        text_matches = [
            match.group(0)
            for match in numbered.finditer(text)
            if int(match.group("number")) != 317
        ]
        if text_matches:
            violations.append(f"content:{relative}")
    assert not violations, "retired campaign identity remains:\n" + "\n".join(violations)


def test_physical_oscillator_name_is_not_used_as_software_identity() -> None:
    digits = "".join(("3", "1", "7"))
    identity = re.compile("cx" + digits, re.IGNORECASE)
    permitted_physical_references = re.compile(
        "|".join(
            (
                r"\bCX" + digits + r"\b",
                r"OTIS_DOMAIN_H1_CX" + digits + r"_OCXO_10MHZ",
                r"h1_cx" + digits + r"_ocxo_10mhz",
            )
        )
    )
    violations: list[str] = []
    for path in _current_files():
        relative = path.as_posix()
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        checked_path = permitted_physical_references.sub("", relative)
        checked_text = permitted_physical_references.sub("", text)
        if identity.search(checked_path) or identity.search(checked_text):
            violations.append(relative)
    assert not violations, (
        "physical oscillator name is used as a software/campaign identity:\n"
        + "\n".join(violations)
    )


def test_historical_compatibility_is_not_an_executable_pytest_surface() -> None:
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    runner = (
        ROOT
        / "firmware/arduino/validation/scripts/run_no_hardware_checks.py"
    ).read_text(encoding="utf-8")
    marker = "histor" + "ical"
    assert marker + ":" not in configuration
    assert f'"{marker}"' not in runner


def test_retired_split_lifecycle_records_are_absent_from_current_code() -> None:
    retired = (
        "A" + "T2",
        "A" + "H2",
        "active_" + "timing_sidecar",
        "timing_record_" + "sequence",
        "active_transactions_" + "v1",
        "active_hybrid_decisions_" + "v1",
    )
    violations: list[str] = []
    for path in _current_files():
        relative = path.as_posix()
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        matched = [token for token in retired if token in relative or token in text]
        if matched:
            violations.append(f"{relative}: {', '.join(matched)}")
    assert not violations, "retired split lifecycle record remains:\n" + "\n".join(
        violations
    )
