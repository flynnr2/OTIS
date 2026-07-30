#!/usr/bin/env python3
"""Build the intentional OTIS Arduino firmware matrix with exact provenance."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = REPO_ROOT / "firmware" / "arduino" / "firmware_matrix.json"
SKETCH = REPO_ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
CONFIG_HEADER = SKETCH / "otis_config.h"
BUILDER_VERSION = 1
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
DEFINE_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
DEFINE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_()+.,:+*/<>=!-]+$")
HEX40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PROFILE_DEFINES = {
    "OTIS_FIRMWARE_CONFIG_ID",
    "OTIS_FIRMWARE_GIT_COMMIT",
}


class MatrixError(RuntimeError):
    pass


def _run(
    arguments: list[str],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise MatrixError(f"required executable is unavailable: {arguments[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise MatrixError(
            f"command failed ({' '.join(arguments)}): {detail}"
        ) from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read matrix {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MatrixError("firmware matrix root must be an object")
    return value


def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    matrix = _load_json(path)
    if matrix.get("schema_version") != 1:
        raise MatrixError("firmware matrix schema_version must be 1")
    if matrix.get("builder_id") != "otis_firmware_matrix_v1":
        raise MatrixError("firmware matrix builder_id is unsupported")

    target = matrix.get("target")
    toolchain = matrix.get("toolchain")
    profiles = matrix.get("profiles")
    if not isinstance(target, dict) or not isinstance(toolchain, dict):
        raise MatrixError("firmware matrix target and toolchain must be objects")
    if not isinstance(profiles, list) or not profiles:
        raise MatrixError("firmware matrix profiles must be a non-empty array")

    required_target = {
        "fqbn",
        "board",
        "core_provider",
        "core_architecture",
        "core_version",
        "core_archive_sha256",
    }
    required_toolchain = {
        "packager",
        "name",
        "version",
        "compiler",
        "compiler_version",
    }
    if required_target - set(target):
        raise MatrixError(
            f"firmware matrix target is missing {sorted(required_target - set(target))}"
        )
    if required_toolchain - set(toolchain):
        raise MatrixError(
            "firmware matrix toolchain is missing "
            f"{sorted(required_toolchain - set(toolchain))}"
        )
    if not HEX64_PATTERN.fullmatch(str(target["core_archive_sha256"])):
        raise MatrixError("target core_archive_sha256 must be lowercase SHA-256")

    seen: set[str] = set()
    pass_count = 0
    fail_count = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            raise MatrixError("each firmware profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not PROFILE_ID_PATTERN.fullmatch(
            profile_id
        ):
            raise MatrixError(f"invalid firmware profile id: {profile_id!r}")
        if profile_id in seen:
            raise MatrixError(f"duplicate firmware profile id: {profile_id}")
        seen.add(profile_id)
        expectation = profile.get("expect")
        if expectation == "pass":
            pass_count += 1
            if "expected_error" in profile:
                raise MatrixError(
                    f"supported profile {profile_id} must not name expected_error"
                )
        elif expectation == "fail":
            fail_count += 1
            if not isinstance(profile.get("expected_error"), str) or not profile[
                "expected_error"
            ]:
                raise MatrixError(
                    f"invalid profile {profile_id} must name expected_error"
                )
        else:
            raise MatrixError(
                f"profile {profile_id} expect must be 'pass' or 'fail'"
            )
        defines = profile.get("defines")
        if not isinstance(defines, dict) or not defines:
            raise MatrixError(f"profile {profile_id} defines must be an object")
        for name, value in defines.items():
            if (
                not isinstance(name, str)
                or not DEFINE_NAME_PATTERN.fullmatch(name)
                or name.startswith("OTIS_BUILD_")
                or name in FORBIDDEN_PROFILE_DEFINES
            ):
                raise MatrixError(
                    f"profile {profile_id} may not define generated identity {name!r}"
                )
            if (
                not isinstance(value, str)
                or not value
                or not DEFINE_VALUE_PATTERN.fullmatch(value)
            ):
                raise MatrixError(
                    f"profile {profile_id} has unsafe define value for {name}: {value!r}"
                )
    if pass_count == 0 or fail_count == 0:
        raise MatrixError(
            "firmware matrix must contain supported and expected-fail profiles"
        )
    return matrix


def configuration_payload(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    config_source_sha256: str | None = None,
) -> dict[str, Any]:
    config_source_sha256 = (
        config_source_sha256
        if config_source_sha256 is not None
        else sha256(CONFIG_HEADER.read_bytes()).hexdigest()
    )
    if not HEX64_PATTERN.fullmatch(config_source_sha256):
        raise MatrixError("config_source_sha256 must be lowercase SHA-256")
    return {
        "schema_version": 1,
        "fqbn": matrix["target"]["fqbn"],
        "profile_id": profile["id"],
        "defines": dict(sorted(profile["defines"].items())),
        "config_source_sha256": config_source_sha256,
    }


def configuration_hash(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    config_path: Path = CONFIG_HEADER,
) -> str:
    return _sha256_json(
        configuration_payload(
            matrix,
            profile,
            config_source_sha256=sha256(config_path.read_bytes()).hexdigest(),
        )
    )


def _git_identity(repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if not HEX40_PATTERN.fullmatch(commit):
        raise MatrixError(f"Git returned a malformed commit identity: {commit!r}")
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
    ).stdout
    return commit, "dirty" if status else "clean"


def source_input_hash(
    *,
    sketch: Path = SKETCH,
    matrix_path: Path = DEFAULT_MATRIX,
    builder_path: Path = Path(__file__).resolve(),
) -> str:
    def source_name(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return resolved.as_posix()

    paths = sorted(
        [path for path in sketch.rglob("*") if path.is_file()]
        + [matrix_path.resolve(), builder_path.resolve()],
        key=source_name,
    )
    digest = sha256()
    for path in paths:
        relative = source_name(path).encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _build_properties(board_details: dict[str, Any]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for item in board_details.get("build_properties", []):
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        properties[key] = value
    return properties


def verify_environment(
    matrix: dict[str, Any],
    *,
    arduino_cli: str = "arduino-cli",
) -> dict[str, str]:
    cli = json.loads(
        _run([arduino_cli, "version", "--format", "json"]).stdout
    )
    expected_cli = str(matrix["arduino_cli_version"])
    actual_cli = str(cli.get("VersionString", ""))
    if actual_cli != expected_cli:
        raise MatrixError(
            f"Arduino CLI version mismatch: expected {expected_cli}, found {actual_cli}"
        )

    target = matrix["target"]
    details = json.loads(
        _run(
            [
                arduino_cli,
                "board",
                "details",
                "--fqbn",
                str(target["fqbn"]),
                "--format",
                "json",
            ]
        ).stdout
    )
    checks = {
        "FQBN": (target["fqbn"], details.get("fqbn")),
        "core provider": (
            target["core_provider"],
            details.get("package", {}).get("name"),
        ),
        "core architecture": (
            target["core_architecture"],
            details.get("platform", {}).get("architecture"),
        ),
        "core version": (target["core_version"], details.get("version")),
        "core archive checksum": (
            f"SHA-256:{target['core_archive_sha256']}",
            details.get("platform", {}).get("checksum"),
        ),
    }
    for label, (expected, actual) in checks.items():
        if actual != expected:
            raise MatrixError(
                f"{label} mismatch: expected {expected!r}, found {actual!r}"
            )

    toolchain = matrix["toolchain"]
    dependency = next(
        (
            item
            for item in details.get("tools_dependencies", [])
            if item.get("packager") == toolchain["packager"]
            and item.get("name") == toolchain["name"]
        ),
        None,
    )
    if dependency is None:
        raise MatrixError("pinned compiler toolchain is absent from board dependencies")
    if dependency.get("version") != toolchain["version"]:
        raise MatrixError(
            "compiler toolchain version mismatch: expected "
            f"{toolchain['version']}, found {dependency.get('version')}"
        )

    properties = _build_properties(details)
    toolchain_name = str(toolchain["name"])
    path_key = f"runtime.tools.{toolchain_name}.path"
    tool_root = properties.get(path_key)
    compiler_prefix = properties.get("build.toolchain")
    compiler_package = properties.get("build.toolchainpkg")
    if not tool_root or not compiler_prefix:
        raise MatrixError("board details do not expose the selected compiler path")
    if compiler_package != toolchain_name:
        raise MatrixError(
            f"board selects compiler package {compiler_package!r}, "
            f"not {toolchain_name!r}"
        )
    compiler_path = Path(tool_root) / "bin" / str(toolchain["compiler"])
    if str(toolchain["compiler"]) != f"{compiler_prefix}-g++":
        raise MatrixError(
            "compiler executable mismatch: board selects "
            f"{compiler_prefix!r}, matrix names {toolchain['compiler']!r}"
        )
    compiler_line = _run([str(compiler_path), "--version"]).stdout.splitlines()[0]
    expected_fragment = f" {toolchain['compiler_version']}"
    if not compiler_line.endswith(expected_fragment):
        raise MatrixError(
            "compiler version mismatch: expected "
            f"{toolchain['compiler_version']!r}, found {compiler_line!r}"
        )

    return {
        "arduino_cli_version": actual_cli,
        "compiler_identity": (
            f"{toolchain_name}@{toolchain['version']}/"
            f"{toolchain['compiler']}@{toolchain['compiler_version']}"
        ),
        "compiler_path": str(compiler_path),
    }


def build_provenance(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    environment: dict[str, str],
    *,
    git_commit: str,
    source_state: str,
    source_sha256: str,
) -> dict[str, Any]:
    if not HEX64_PATTERN.fullmatch(source_sha256):
        raise MatrixError("source_sha256 must be lowercase SHA-256")
    config = configuration_payload(matrix, profile)
    config_sha256 = _sha256_json(config)
    invocation_payload = {
        "builder_id": matrix["builder_id"],
        "builder_version": BUILDER_VERSION,
        "git_commit": git_commit,
        "source_state": source_state,
        "source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "arduino_cli_version": environment["arduino_cli_version"],
        "core_provider": matrix["target"]["core_provider"],
        "core_version": matrix["target"]["core_version"],
        "toolchain": (
            f"{matrix['toolchain']['name']}@{matrix['toolchain']['version']}"
        ),
        "compiler": environment["compiler_identity"],
    }
    return {
        "schema_version": 1,
        "source": {
            "git_commit": git_commit,
            "state": source_state,
            "sha256": source_sha256,
        },
        "configuration": {
            **config,
            "sha256": config_sha256,
        },
        "target": dict(matrix["target"]),
        "toolchain": {
            **matrix["toolchain"],
            "compiler_identity": environment["compiler_identity"],
        },
        "invocation": {
            "builder_id": matrix["builder_id"],
            "arduino_cli_version": environment["arduino_cli_version"],
            "id": _sha256_json(invocation_payload),
        },
    }


def provenance_header(provenance: dict[str, Any]) -> str:
    source = provenance["source"]
    config = provenance["configuration"]
    target = provenance["target"]
    toolchain = provenance["toolchain"]
    invocation = provenance["invocation"]
    generated = {
        "OTIS_BUILD_GIT_COMMIT": source["git_commit"],
        "OTIS_BUILD_SOURCE_STATE": source["state"],
        "OTIS_BUILD_SOURCE_SHA256": source["sha256"],
        "OTIS_BUILD_CONFIG_SHA256": config["sha256"],
        "OTIS_BUILD_PROFILE_ID": config["profile_id"],
        "OTIS_BUILD_FQBN": target["fqbn"],
        "OTIS_BUILD_CORE_PROVIDER": target["core_provider"],
        "OTIS_BUILD_CORE_VERSION": target["core_version"],
        "OTIS_BUILD_TOOLCHAIN": (
            f"{toolchain['name']}@{toolchain['version']}"
        ),
        "OTIS_BUILD_COMPILER": toolchain["compiler_identity"],
        "OTIS_BUILD_ARDUINO_CLI_VERSION": invocation[
            "arduino_cli_version"
        ],
        "OTIS_BUILD_INVOCATION_ID": invocation["id"],
    }
    lines = [
        "#ifndef OTIS_BUILD_PROVENANCE_GENERATED_H",
        "#define OTIS_BUILD_PROVENANCE_GENERATED_H",
        "",
        "// Generated by tools/firmware_matrix.py. Do not hand-edit or commit.",
        "#define OTIS_BUILD_PROVENANCE_GENERATED 1",
    ]
    for name, value in sorted(generated.items()):
        encoded = json.dumps(str(value), ensure_ascii=True)
        lines.append(f"#define {name} {encoded}")
    lines.extend(["", "#endif", ""])
    return "\n".join(lines)


def compiler_defines(profile: dict[str, Any]) -> list[str]:
    return [
        f"-D{name}={value}"
        for name, value in sorted(profile["defines"].items())
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _selected_profiles(
    matrix: dict[str, Any],
    requested: list[str],
    supported_only: bool,
) -> list[dict[str, Any]]:
    profiles = matrix["profiles"]
    by_id = {profile["id"]: profile for profile in profiles}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise MatrixError(f"unknown firmware profiles: {unknown}")
    selected = [by_id[item] for item in requested] if requested else list(profiles)
    if supported_only:
        selected = [profile for profile in selected if profile["expect"] == "pass"]
    if not selected:
        raise MatrixError("no firmware profiles selected")
    return selected


def _compile_profile(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    provenance: dict[str, Any],
    output_dir: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    profile_dir = output_dir / profile["id"]
    build_dir = profile_dir / "build"
    artifacts_dir = profile_dir / "artifacts"
    build_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for stale_artifact in artifacts_dir.iterdir():
        if stale_artifact.is_file():
            stale_artifact.unlink()
    generated_header = profile_dir / "otis_build_provenance.generated.h"
    generated_header.write_text(
        provenance_header(provenance),
        encoding="utf-8",
    )
    flags = " ".join(
        [f"-include{generated_header}", *compiler_defines(profile)]
    )
    command = [
        arduino_cli,
        "compile",
        "--clean",
        "--fqbn",
        str(matrix["target"]["fqbn"]),
        "--build-path",
        str(build_dir),
        "--output-dir",
        str(artifacts_dir),
        "--build-property",
        f"compiler.cpp.extra_flags={flags}",
        str(SKETCH),
    ]
    result = _run(command, check=False)
    combined = result.stdout + result.stderr
    (profile_dir / "build.log").write_text(combined, encoding="utf-8")

    expected = profile["expect"]
    passed = result.returncode == 0
    outcome_matches = passed if expected == "pass" else not passed
    error_matched = True
    if expected == "fail":
        error_matched = profile["expected_error"] in combined
        outcome_matches = outcome_matches and error_matched
    if passed:
        _write_json(
            artifacts_dir / "firmware_build_provenance.json",
            provenance,
        )
    return {
        "profile_id": profile["id"],
        "expect": expected,
        "returncode": result.returncode,
        "outcome": "pass" if passed else "fail",
        "expected_error_matched": error_matched,
        "verified": outcome_matches,
        "config_sha256": provenance["configuration"]["sha256"],
        "invocation_id": provenance["invocation"]["id"],
        "build_log": str((profile_dir / "build.log").resolve()),
        "provenance": (
            str(
                (
                    artifacts_dir / "firmware_build_provenance.json"
                ).resolve()
            )
            if passed
            else None
        ),
    }


def run_matrix(
    matrix: dict[str, Any],
    profiles: list[dict[str, Any]],
    output_dir: Path,
    *,
    arduino_cli: str = "arduino-cli",
    matrix_path: Path = DEFAULT_MATRIX,
) -> list[dict[str, Any]]:
    environment = verify_environment(matrix, arduino_cli=arduino_cli)
    git_commit, source_state = _git_identity()
    source_sha256 = source_input_hash(matrix_path=matrix_path)
    results: list[dict[str, Any]] = []
    for profile in profiles:
        provenance = build_provenance(
            matrix,
            profile,
            environment,
            git_commit=git_commit,
            source_state=source_state,
            source_sha256=source_sha256,
        )
        print(
            f"[{profile['expect']}] {profile['id']} "
            f"config={provenance['configuration']['sha256'][:12]}",
            flush=True,
        )
        result = _compile_profile(
            matrix,
            profile,
            provenance,
            output_dir,
            arduino_cli,
        )
        results.append(result)
        print(
            f"  outcome={result['outcome']} verified={result['verified']}",
            flush=True,
        )
    try:
        matrix_name = str(matrix_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        matrix_name = str(matrix_path.resolve())
    summary = {
        "schema_version": 1,
        "matrix": matrix_name,
        "git_commit": git_commit,
        "source_state": source_state,
        "all_verified": all(result["verified"] for result in results),
        "results": results,
    }
    _write_json(output_dir / "matrix_summary.json", summary)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile the pinned, intentional OTIS Arduino firmware matrix."
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX,
        help="Pinned matrix JSON (default: firmware/arduino/firmware_matrix.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "build" / "firmware_matrix",
        help="Ignored build/artifact directory.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Build one profile id; repeat to select several.",
    )
    parser.add_argument(
        "--supported-only",
        action="store_true",
        help="Skip expected-fail guard profiles.",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Verify the pinned CLI/core/toolchain without compiling.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the intentional matrix without inspecting the toolchain.",
    )
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable (version remains pinned).",
    )
    args = parser.parse_args(argv)

    try:
        matrix = load_matrix(args.matrix.resolve())
        selected = _selected_profiles(
            matrix, list(args.profile), args.supported_only
        )
        if args.list:
            for profile in selected:
                print(
                    f"{profile['id']}\t{profile['expect']}\t"
                    f"{profile.get('purpose', '')}"
                )
            return 0
        if args.check_environment:
            environment = verify_environment(
                matrix, arduino_cli=args.arduino_cli
            )
            print(json.dumps(environment, indent=2, sort_keys=True))
            return 0
        results = run_matrix(
            matrix,
            selected,
            args.output_dir.resolve(),
            arduino_cli=args.arduino_cli,
            matrix_path=args.matrix.resolve(),
        )
    except (MatrixError, json.JSONDecodeError) as exc:
        print(f"firmware matrix error: {exc}", file=sys.stderr)
        return 2
    return 0 if all(result["verified"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
