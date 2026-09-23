from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


@pytest.fixture(scope="module")
def classifier_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path_factory.mktemp("response_classifier") / "classifier"
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(FIRMWARE),
            str(ROOT / "tests/cpp/response_classifier_contract_harness.cpp"),
            str(FIRMWARE / "otis_regulation_transaction.cpp"),
            "-o", str(executable),
        ],
        check=True,
    )
    return executable


@pytest.mark.parametrize(
    ("pre", "post", "delta", "classification"),
    [
        (-0.01, -0.006, 20, "healthy_detected"),
        (-0.01, -0.009, 20, "healthy_indeterminate_near_resolution"),
        (-0.01, -0.014, 20, "wrong_sign"),
        (0.01, 0.02, 20, "growing_error"),
        (-0.01, 0.01, 20, "excess_response"),
        (-0.01, -0.006, 0, "measurement_or_actuator_fault"),
    ],
)
def test_response_classifier_retains_numeric_verdicts(
    classifier_executable: Path,
    pre: float,
    post: float,
    delta: int,
    classification: str,
) -> None:
    result = subprocess.run(
        [str(classifier_executable)],
        input=f"{pre} {post} {delta}\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.split(",", 1)[0] == classification
