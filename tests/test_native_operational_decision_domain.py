"""Exercise the actual native64 decision/capture domain boundary predicate."""
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
FW=ROOT/'firmware/arduino/otis_nano_rp2040_connect'
def test_native_decision_never_uses_pps_extension_as_timer(tmp_path):
    source=(FW/'otis_frequency_regulation_live.cpp').read_text()
    start=source.index('  uint64_t active_decision_timestamp_ticks = 0u;')
    end=source.index('  const uint32_t active_decision_timestamp_s',start)
    predicate=source[start:end]
    harness=tmp_path/'decision.cpp'
    harness.write_text('''#include <cassert>
#include <cstdint>
#include "otis_firmware_host_contract.generated.h"
struct Source { uint32_t reference_timestamp_ticks; uint32_t timestamp_uncertainty_ticks; };
uint64_t admit(uint64_t captured,uint64_t now,uint32_t raw,uint32_t uncertainty=16) {
 bool boundary_extended=uint32_t(captured)==raw;
 uint64_t current_boundary_extended_ticks=captured,operational_decision_ticks=now;
 Source record={raw,uncertainty};const auto *observation=&record;
'''+predicate+'''return active_decision_timestamp_ticks;
}
int main() {
 constexpr uint64_t wrap=uint64_t(1)<<32;
 assert(admit(17*wrap+500,17*wrap+600,500)==17*wrap+600);
 assert(admit(wrap-20,wrap+100,uint32_t(wrap-20))==wrap+100);
 assert(admit(17*wrap+500,600,500)==0); // truncating native now never reconstructs a new era
 assert(admit(17*wrap+500,17*wrap+600,501)==0);
 assert(admit(1000,999,1000)==0);
 assert(admit(1000,60000984,1000)==60000984); // exact uncertainty-inclusive bound
 assert(admit(1000,60000985,1000)==0);
 assert(admit(1000,61001000,1000)==0);
 assert(admit(0,wrap,0)==0); // complete-wrap ambiguity never passes low-word equality
}
''')
    compiler=shutil.which('c++');assert compiler
    binary=tmp_path/'decision'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(FW),str(harness),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)

def test_startup_inhibition_cannot_restart_at_millis_rollover(tmp_path):
    source=(FW/'otis_count_observation.cpp').read_text()
    start=source.index('void update_startup_inhibit(')
    end=source.index('\nvoid record_window_quality',start)
    production=source[start:end]
    harness=tmp_path/'startup.cpp'
    harness.write_text('''#include <cassert>
#include <cstdint>
struct OtisRuntimeState { struct {uint64_t startup_inhibit_start_ticks;uint32_t startup_inhibit_elapsed_s;bool startup_inhibit_active;} tcxo;};
struct OtisCountObservationConfig {uint32_t startup_inhibit_ms;};
uint64_t clock_ticks;
uint64_t time_us_64(){return clock_ticks;}
'''+production+'''
int main(){
 OtisRuntimeState state={};state.tcxo.startup_inhibit_start_ticks=1234567;
 OtisCountObservationConfig config={600000};
 clock_ticks=state.tcxo.startup_inhibit_start_ticks+600000000ull-1;
 update_startup_inhibit(&state,&config,uint32_t(clock_ticks/1000));assert(state.tcxo.startup_inhibit_active);
 ++clock_ticks;update_startup_inhibit(&state,&config,uint32_t(clock_ticks/1000));assert(!state.tcxo.startup_inhibit_active);
 clock_ticks=(uint64_t(1)<<32)*1000+state.tcxo.startup_inhibit_start_ticks;
 update_startup_inhibit(&state,&config,uint32_t(clock_ticks/1000));assert(!state.tcxo.startup_inhibit_active);
 assert(state.tcxo.startup_inhibit_elapsed_s==4294967);
}
''')
    compiler=shutil.which('c++');assert compiler
    binary=tmp_path/'startup'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(harness),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
