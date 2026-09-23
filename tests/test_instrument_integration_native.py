"""Actual live adapter, partition mailboxes, command parser and executor admission."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
FW=ROOT/'firmware/arduino/otis_nano_rp2040_connect'
@pytest.fixture(scope='session')
def integration_native(tmp_path_factory):
    compiler=shutil.which('c++'); assert compiler
    output=tmp_path_factory.mktemp('instrument_integration')/'harness'
    sources=['otis_emit.cpp','otis_instrument.cpp','otis_instrument_executor.cpp','otis_adaptive_hybrid_regulation_live.cpp','otis_adaptive_hybrid_regulation.cpp','otis_adaptive_hybrid_wide.cpp','otis_regulation_transaction.cpp','otis_dual_core_partition.cpp','otis_serial_command.cpp']
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined,address','-fno-omit-frame-pointer','-DOTIS_BUILD_SOURCE_SHA256="host_test"','-DOTIS_BUILD_CONFIG_SHA256="host_test"','-I',str(FW),str(ROOT/'tests/cpp/instrument_integration_harness.cpp'),*(str(FW/n) for n in sources),'-o',str(output)],check=True)
    return output
@pytest.mark.parametrize('scenario',['boot_repeated','executor','commands'])
def test_integration(integration_native,scenario):
    r=subprocess.run([str(integration_native),scenario],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

def test_application_reaches_first_consumers_before_capture_decision():
    source=(FW/'otis_nano_rp2040_connect.ino').read_text()
    inputs=source[source.index('void service_dual_core_timing_inputs'):source.index('void service_instrument_executor')]
    assert inputs.index('propagate_regulation_applied_epoch_to_previews_exact')<inputs.index('otis_adaptive_hybrid_regulation_live_confirm_consumers')
    loop=source[source.index('void loop1()'):source.index('void loop()')]
    assert loop.index('service_dual_core_timing_inputs();')<loop.index('drain_reference_snapshots();')
    propagation=source[source.index('bool propagate_regulation_applied_epoch_to_previews_exact'):source.index('void service_dual_core_timing_inputs')]
    assert 'otis_frequency_regulation_live_on_dac_applied_epoch_exact' in propagation
    assert 'otis_phase_preview_live_update_applied_code' in propagation


def test_actual_emitted_wire_matches_canonical_layout(integration_native):
    import csv,json
    contract=json.loads((ROOT/'data_contracts/otis_firmware_host_contract_v1.json').read_text())
    layouts={tag:spec for spec in contract['records'].values() for tag in spec['record_types']}
    result=subprocess.run([str(integration_native),'wire'],capture_output=True,text=True,check=True)
    records=list(csv.reader(result.stdout.splitlines()))
    tags={row[0] for row in records}
    assert {'ICM','IST','IWR','IAP','IDC','IRS'}<=tags
    prior=0
    for row in records:
        assert len(row)==len(layouts[row[0]]['fields']),(row,layouts[row[0]]['fields'])
        assert int(row[2])>prior
        prior=int(row[2])


def test_actual_firmware_snapshot_and_receipt_reach_recorder(integration_native, tmp_path):
    from host.otis_tools.instrument_recorder import InstrumentRecorder, RecorderConfig
    wire = subprocess.run([str(integration_native), 'snapshot_wire'],
                          capture_output=True, check=True).stdout
    recorder = InstrumentRecorder(RecorderConfig(device='unused', run_dir=tmp_path))
    recorder.started_utc = 'native-integration'
    recorder.pending_command = {'session': 18446744073709551601, 'sequence': 1}
    # Exercise arbitrary serial chunk boundaries, including within the 64-bit
    # boot identity and matching begin/complete status markers.
    for offset in range(0, len(wire), 7):
        recorder._observe(wire[offset:offset + 7])
    status = recorder.instrument
    assert status is not None
    assert status['session'] == 18446744073709551601
    assert status['fields']['capture_session'] == '17'
    assert status['mode'] == status['requested_mode'] == 'OBSERVE_HOLD'
    assert status['applied_code_known'] and status['applied_code'] == 0xA84D
    assert status['dac_epoch'] == 1
    assert status['completed_command_sequence'] == 1
    assert recorder.invalid_status == 0
    assert recorder.pending_command is None
    assert recorder.last_receipt['result'] == 'ACCEPTED'
    assert recorder.last_receipt['session'] == status['session']
