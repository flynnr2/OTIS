"""Bounded transport feasibility, using unchanged real PIO instruction words.
This is not an ISR implementation, service-latency proof, or qualification.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import verify_pio_snapshot as p

p.OSC_HZ = 10_000_000


def run(pulses, *, masked_until=0, finish=1600):
    machine = p.PioMachine()
    osc = p.TwoFlopSynchronizer(True, True)
    ref = p.TwoFlopSynchronizer(False, False)
    records = []
    service_at = None
    delivered = 0
    for cycle in range(finish):
        machine.step(
            cycle,
            osc.sample((cycle * 10 % 133) < 66.5),
            ref.sample(any(a <= cycle < b for a, b in pulses)),
            drain_fifo=False,
        )
        # The level source remains asserted while data is queued. Repeated
        # notifications have no record identity: only FIFO reads do.
        if machine.fifo_depth and service_at is None:
            service_at = max(cycle + 3, masked_until)
        if service_at is not None and cycle >= service_at:
            depth = machine.fifo_depth
            for _ in range(min(depth, 8)):
                word = machine.snapshots[delivered]
                records.append(
                    {
                        "ordinal": delivered,
                        "count": word.down_counter,
                        "service_cycle": cycle,
                        "batch_ambiguous": depth > 1,
                        "capture_fault": machine.rx_stall,
                    }
                )
                delivered += 1
                machine.fifo_depth -= 1
            service_at = None
    assert [r["ordinal"] for r in records] == list(range(len(records)))
    assert [r["count"] for r in records] == [
        x.down_counter for x in machine.snapshots[: len(records)]
    ]
    return machine, records


normal = [(100, 140), (1000, 1040)]
a, ra = run(normal)
assert len(ra) == 2 and not any(r["batch_ambiguous"] for r in ra)
# Search a small declared phase range, rather than assume a particular narrow
# input must be invisible to the PIO. GPIO notification itself is not modeled.
miss = None
for start in range(500, 540):
    b, rb = run(normal + [(start, start + 1)])
    if len(rb) == 2:
        miss = (start, rb)
        break
assert miss is not None
# A PIO-recognized extra edge remains a real extra raw FIFO word; an IRQ-only
# diagnostic notification has no way to add a count record in this transport.
c, rc = run(normal + [(500, 540)])
assert len(rc) == 3
# Delayed service coalesces wakeups, not word identity. These service times
# cannot stand in for distinct PPS event times, so mark the batch ambiguous.
d, rd = run(normal, masked_until=1200)
assert len(rd) == 2 and all(r["batch_ambiguous"] for r in rd)
assert len({r["service_cycle"] for r in rd}) == 1
# Show the physical limitation explicitly: FIFO-only drainage must not be
# advertised as 128-word hardware buffering while IRQs are masked.
e, re = run(
    [(100 + i * 100, 140 + i * 100) for i in range(10)], masked_until=2000, finish=1500
)
assert e.rx_stall and e.fifo_depth == 8 and len(e.snapshots) == 8 and not re
print(
    json.dumps(
        {
            "scope": "transport model only; no firmware or qualification change",
            "unchanged_pio_words": len(p.PROGRAM_WORDS),
            "cases": {
                "ordinary_two_boundaries": len(ra),
                "one_cycle_pulse_missed_at": miss[0],
                "missed_pulse_extra_fifo_records": len(miss[1]) - len(ra),
                "recognized_extra_pulse_raw_records": len(rc),
                "coalesced_service_records": len(rd),
                "coalesced_service_marked_ambiguous": True,
                "fifo_overload_rxstall": e.rx_stall,
                "retained_words_at_overload": len(e.snapshots),
            },
        },
        indent=2,
    )
)
