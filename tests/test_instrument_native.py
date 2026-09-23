"""Execute the firmware owner and actual selected policy through complete operations."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / 'firmware/arduino/otis_nano_rp2040_connect'

@pytest.fixture(scope='session')
def instrument_native(tmp_path_factory):
    compiler = shutil.which('c++')
    assert compiler, 'Native firmware verification requires a C++ compiler'
    output = tmp_path_factory.mktemp('instrument') / 'instrument'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined,address', '-fno-omit-frame-pointer',
                    '-I', str(FW), str(ROOT/'tests/cpp/instrument_harness.cpp'),
                    *(str(FW/name) for name in ('otis_instrument.cpp',
                    'otis_adaptive_hybrid_regulation.cpp', 'otis_adaptive_hybrid_wide.cpp',
                    'otis_regulation_transaction.cpp')), '-o', str(output)], check=True)
    return output

@pytest.mark.parametrize('scenario', ['boot_modes','fixed_characterize','repeated',
    'pending_modes','timed_auto','reference_recovery','metadata_recovery',
    'metadata_response_interruption','metadata_released_application',
    'metadata_during_startup','timed_auto_delayed_overflow',
    'failure_identity','timeout_rejection'])
def test_instrument_complete_operations(instrument_native, scenario):
    result = subprocess.run([str(instrument_native), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
