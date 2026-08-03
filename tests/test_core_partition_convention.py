from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_DOCUMENTS = (
    ROOT / "docs/10_REFERENCE_ARCHITECTURE/CORE_PARTITIONING.md",
    ROOT / "docs/10_REFERENCE_ARCHITECTURE/ARCHITECTURE_DIAGRAMS.md",
    ROOT / "docs/40_HARDWARE/MVP_HARDWARE_REFERENCE.md",
    ROOT / "docs/40_HARDWARE/RP2040_Other_Capabilities.md",
    ROOT / "docs/50_SOFTWARE/RP2040_CAPTURE_ARCHITECTURE.md",
    ROOT / "docs/50_SOFTWARE/HOST_ARCHITECTURE.md",
    ROOT / "docs/90_ROADMAP/RP2040_FIRST_MVP_NOTE.md",
)


def test_programme_core_number_convention_is_consistent() -> None:
    forbidden = (
        "Core 0             timing and discipline core",
        "Core 1             service and instrumentation core",
        "Core 0 remains timing-focused",
        "Core 1 remains service-focused",
        "Core 0 — Sacred Timing",
        "Core 1 — Disposable Services",
        "Core 0 | timing capture",
        "Core 1 | USB/serial transport",
    )

    for path in CANONICAL_DOCUMENTS:
        text = path.read_text(encoding="utf-8")
        assert not any(phrase in text for phrase in forbidden), path

    partition = CANONICAL_DOCUMENTS[0].read_text(encoding="utf-8")
    assert "Core 0             service, I/O and instrumentation core" in partition
    assert "Core 1             protected timing and discipline core" in partition
    assert "stall Core 1" in partition
