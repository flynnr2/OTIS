"""PIO recognition brackets must not be promoted to exact PPS timestamps."""
import shutil
import subprocess
from pathlib import Path


def test_whole_recognition_interval_and_freshness_are_required(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "bounds.cpp"
    source.write_text(r'''
#include <cassert>
#include "otis_reference_acceptance_live.h"
#include "otis_reference_acceptance_policy.generated.h"
using D = OtisReferenceAcceptanceDisposition;
using R = OtisReferenceAcceptanceReason;
struct Trace {
  OtisReferenceAcceptanceLive selector{OTIS_REFERENCE_ACCEPTANCE_POLICY};
  uint64_t ticks = 10000000;
  OtisReferenceAcceptanceObservation raw{1, 0, 0, uint32_t(ticks), UINT32_MAX, 0, 16, 50};
  OtisReferenceAcceptanceOutcome observe(uint64_t delay=0) {
    return selector.observe(raw,ticks,ticks+delay,10000);
  }
  OtisReferenceAcceptanceOutcome step(uint32_t dt=1000000, uint32_t uncertainty=50) {
    ticks+=dt; ++raw.snapshot_sequence; ++raw.reference_sequence;
    raw.reference_timestamp_ticks=uint32_t(ticks);
    raw.cumulative_down_counter-=dt*10;
    raw.timestamp_uncertainty_ticks=uncertainty;
    return observe();
  }
  void acquire() {
    observe(); for(int i=0;i<8;++i) step();
    assert(selector.status().tracking);
  }
};
int main() {
  Trace clean; clean.acquire();
  assert(clean.step().has_span);
  // A PIO-recognized early candidate is raw evidence, never a second owner.
  assert(clean.step(902367).disposition==D::EarlyExcluded);
  auto span=clean.step(97633);
  assert(span.has_span && span.counted_edges==10000000 && span.excluded_candidate_count==1);
  // Point service time alone is inside tolerance, but the bracket crosses it.
  Trace low; low.acquire(); auto q=low.step(998750,1);
  assert(q.disposition==D::QualificationLost && q.reason==R::ObservationAgeAmbiguous);
  Trace high; high.acquire(); q=high.step(1001250,1);
  assert(q.reason==R::ObservationAgeAmbiguous && !q.has_span);
  Trace exact; exact.acquire();
  assert(exact.step(998800,50).has_span); // Entire interval [998750,998850].
  Trace unknown; unknown.acquire(); q=unknown.step(1000000,UINT32_MAX);
  assert(q.reason==R::ObservationAgeAmbiguous);
  Trace batch; batch.acquire(); batch.raw.snapshot_status=1;
  q=batch.step(); assert(q.reason==R::ObservationAgeAmbiguous);
  // Fresh service does not prove fresh recognition.
  Trace old; old.raw.timestamp_uncertainty_ticks=10001;
  q=old.observe(); assert(q.reason==R::ObservationAgeAmbiguous);
  Trace age; age.acquire(); age.raw.timestamp_uncertainty_ticks=500;
  q=age.observe(9600); assert(q.reason==R::ObservationAgeAmbiguous);
  // Expiry uses the earliest possible anchor, never the service upper bound.
  Trace expiry; expiry.acquire();
  expiry.selector.service(expiry.ticks+1001200); assert(expiry.selector.status().anchor_current);
  expiry.selector.service(expiry.ticks+1001201); assert(!expiry.selector.status().anchor_current);
  Trace wrap; wrap.ticks=(uint64_t(1)<<32)-4500000;
  wrap.raw.reference_timestamp_ticks=uint32_t(wrap.ticks); wrap.acquire();
  assert(wrap.step().has_span);
}
''')
    binary = tmp_path / "bounds"
    subprocess.run([shutil.which("c++") or "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(root / "firmware/arduino/otis_nano_rp2040_connect"), str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
