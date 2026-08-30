from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")
HELPER = FIRMWARE / "otis_forwarded_clock_monitor_interval.h"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")
    return compiler


def test_d6_monitor_interval_reconstruction_is_local_and_deterministic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "forwarded_clock_monitor_interval_check.cpp"
    binary = tmp_path / "forwarded_clock_monitor_interval_check"
    source.write_text(
        textwrap.dedent(
            f"""
            #include <assert.h>
            #include <stdint.h>
            #include "{HELPER}"

            static OtisForwardedClockMonitorIntervalInput snapshot(
                uint32_t session, uint32_t sequence, uint32_t counter,
                uint32_t reference_session, uint32_t reference_sequence,
                uint64_t reference_ticks, uint32_t status = 0u) {{
              return {{session, sequence, counter, reference_session,
                      reference_sequence, reference_ticks, status}};
            }}

            int main(void) {{
              OtisForwardedClockMonitorIntervalReconstructor r = {{}};
              auto first = snapshot(7u, 10u, 0xffffffffu, 12u, 20u, 16000000ull);
              auto anchor = otis_forwarded_clock_monitor_interval_observe(&r, &first);
              assert(anchor.state == OtisForwardedClockMonitorIntervalState::Anchor);
              auto second = snapshot(7u, 11u, 0xff67697fu, 12u, 21u, 32000000ull);
              auto valid = otis_forwarded_clock_monitor_interval_observe(&r, &second);
              assert(valid.state == OtisForwardedClockMonitorIntervalState::ValidInterval);
              assert(valid.interval_valid && valid.interval_count == 10000000u);
              assert(!valid.counter_wrap_handled);
              assert(valid.opening_reference_timestamp_ticks == 16000000ull);
              assert(valid.closing_reference_timestamp_ticks == 32000000ull);

              otis_forwarded_clock_monitor_interval_reset(&r);
              auto wrap_open = snapshot(1u, 0xffffffffu, 5u, 1u, 0xffffffffu, 0ull);
              auto wrap_close = snapshot(1u, 0u, 0xfffffff5u, 1u, 0u, 16000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &wrap_open).state ==
                     OtisForwardedClockMonitorIntervalState::Anchor);
              auto wrapped = otis_forwarded_clock_monitor_interval_observe(&r, &wrap_close);
              assert(wrapped.interval_valid && wrapped.interval_count == 16u);
              assert(wrapped.counter_wrap_handled);

              otis_forwarded_clock_monitor_interval_reset(&r);
              auto a = snapshot(2u, 1u, 30000000u, 4u, 1u, 0ull);
              auto gap = snapshot(2u, 3u, 10000000u, 4u, 3u, 32000000ull);
              auto duplicate = snapshot(2u, 3u, 0u, 4u, 4u, 48000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &a).state ==
                     OtisForwardedClockMonitorIntervalState::Anchor);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &gap).state ==
                     OtisForwardedClockMonitorIntervalState::SnapshotSequenceGap);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &duplicate).state ==
                     OtisForwardedClockMonitorIntervalState::SnapshotSequenceDuplicate);

              otis_forwarded_clock_monitor_interval_reset(&r);
              auto ref_a = snapshot(3u, 1u, 25000000u, 8u, 10u, 0ull);
              auto ref_gap = snapshot(3u, 2u, 15000000u, 8u, 12u, 32000000ull);
              auto ref_dup = snapshot(3u, 3u, 5000000u, 8u, 12u, 48000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &ref_a).state ==
                     OtisForwardedClockMonitorIntervalState::Anchor);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &ref_gap).state ==
                     OtisForwardedClockMonitorIntervalState::ReferenceSequenceGap);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &ref_dup).state ==
                     OtisForwardedClockMonitorIntervalState::ReferenceSequenceDuplicate);

              otis_forwarded_clock_monitor_interval_reset(&r);
              auto status_a = snapshot(4u, 1u, 20000000u, 9u, 1u, 0ull);
              auto bad = snapshot(4u, 2u, 10000000u, 9u, 2u, 16000000ull, 1u);
              auto after_bad = snapshot(4u, 3u, 10000000u, 9u, 3u, 32000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &status_a).state ==
                     OtisForwardedClockMonitorIntervalState::Anchor);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &bad).state ==
                     OtisForwardedClockMonitorIntervalState::LocalStatusNonzero);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &after_bad).state ==
                     OtisForwardedClockMonitorIntervalState::Anchor);

              auto changed_session = snapshot(5u, 0u, 0xffffffffu, 10u, 0u, 48000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &changed_session).state ==
                     OtisForwardedClockMonitorIntervalState::MonitorSessionChange);
              auto ambiguous = snapshot(5u, 1u, 0xff000000u, 10u, 1u, 64000000ull);
              assert(otis_forwarded_clock_monitor_interval_observe(&r, &ambiguous).state ==
                     OtisForwardedClockMonitorIntervalState::AmbiguousCount);

              OtisForwardedClockMonitorIntervalReconstructor replay = {{}};
              auto replay_first = otis_forwarded_clock_monitor_interval_observe(&replay, &first);
              auto replay_second = otis_forwarded_clock_monitor_interval_observe(&replay, &second);
              assert(replay_first.state == anchor.state);
              assert(replay_second.state == valid.state);
              assert(replay_second.interval_count == valid.interval_count);
              return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [_compiler(), "-std=c++17", f"-I{Path.cwd()}", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_d6_interval_helper_has_no_authoritative_or_control_dependencies() -> None:
    source = HELPER.read_text(encoding="utf-8")
    prohibited = (
        "otis_pps_count_boundary",
        "otis_count_observation",
        "otis_dual_core",
        "otis_capture",
        "otis_control",
        "OTIS_PIN_PPS_REFERENCE",
        "D14",
        "D8",
    )
    assert all(token not in source for token in prohibited)
