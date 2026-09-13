"""Native check of the work-branch drain prototype, not the instrument driver."""

import shutil
import subprocess
from pathlib import Path


def test_bounded_fifo_drain_preserves_words_and_faults(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which("c++")
    assert compiler, "FIFO prototype verification requires a native C++ compiler"
    exe = tmp_path / "fifo_drain"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(root),
            str(root / "tests/cpp/pps_fifo_drain_harness.cpp"),
            "-o",
            str(exe),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(exe)], check=True, capture_output=True, text=True)
