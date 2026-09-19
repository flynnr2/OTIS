from copy import deepcopy
import json
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_supervisor as module
from host.otis_tools.adaptive_hybrid_contract import UNATTENDED_72_HOUR_HYBRID_CONTROL
from tests.runtime_fixtures import construct_simulated_supervisor

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/startup_reference_loss_084d27f.json').read_text())


def subject(tmp_path):
    owner = construct_simulated_supervisor(tmp_path, purpose=UNATTENDED_72_HOUR_HYBRID_CONTROL)
    owner.state.update(setup_confirmed_utc='retained', initial_session_id=1,
                       bench_attempt_arm_submission_count=0, arm_pending=False)
    owner._save = lambda: None
    owner._programme_event = lambda *args, **kwargs: None
    health = {tuple(k.split('.', 1)): v for k, v in FIXTURE['health'].items()}
    return owner, health


def test_retained_startup_reference_loss_is_a_wait(tmp_path):
    owner, health = subject(tmp_path)
    faults = module._authoritative_capture_health_faults(health)
    assert len(faults) == 4
    assert owner._startup_reference_wait_permitted(health, faults)


@pytest.mark.parametrize('key,value', [
    ('qualification_started_utc', 'already-qualified'),
    ('qualified_origin_session_id', 1),
    ('host_verification_hold', {'error': 'unrelated'}),
    ('bench_attempt_arm_submission_count', 1),
    ('arm_pending', True),
    ('initial_session_id', 2),
])
def test_startup_exception_never_clears_existing_authority_history(tmp_path, key, value):
    owner, health = subject(tmp_path)
    owner.state[key] = value
    assert not owner._startup_reference_wait_permitted(health, module._authoritative_capture_health_faults(health))


@pytest.mark.parametrize('component,key,value', [
    ('pps_gate', 'capture_state', 'lost'),
    ('pps_gate', 'fifo_continuity', 'unavailable'),
    ('pps_gate', 'snapshot_ring_full_count', '1'),
    ('pps_gate', 'capture_loss_count', '1'),
    ('pps_gate', 'reference_acceptance_state', 'unknown'),
    ('adaptive_hybrid', 'evidence_pending', 'true'),
    ('adaptive_hybrid', 'dac_epoch', '2'),
    ('adaptive_hybrid', 'confirmed_applied_code', '43086'),
    ('adaptive_hybrid', 'setup_reference_eligible', 'missing'),
])
def test_nonreference_faults_cannot_use_startup_exception(tmp_path, component, key, value):
    owner, health = subject(tmp_path)
    health[(component, key)] = value
    assert not owner._startup_reference_wait_permitted(health, module._authoritative_capture_health_faults(health))


def test_wait_requires_current_epoch_full_span_before_first_consumer(tmp_path, monkeypatch):
    owner, health = subject(tmp_path)
    owner._identity_ready = lambda h: True  # Identity is independently exercised above.
    owner.state['startup_reference_wait'] = {
        'session_id': 1, 'resolved_utc': None,
        'frontier_ticks': int(health[(module.LIVE_FRONTIER_COMPONENT, module.LIVE_FRONTIER_TICKS_KEY)]),
    }
    estimate = deepcopy(FIXTURE['recovered_estimate'])
    for component in ('pps_gate', 'adaptive_hybrid'):
        health[(component, 'reference_acceptance_state')] = 'tracking'
        health[(component, 'accepted_anchor_current')] = 'true'
    for key in ('setup_reference_eligible', 'setup_gnss_eligible', 'setup_partition_healthy'):
        health[('adaptive_hybrid', key)] = 'true'
    epoch = estimate['source_acceptance_epoch']
    health[('pps_gate', 'reference_acceptance_epoch')] = epoch
    health[('adaptive_hybrid', 'acceptance_epoch')] = epoch
    ticks = estimate['estimator_timestamp_ticks']
    health[(module.LIVE_FRONTIER_COMPONENT, module.LIVE_FRONTIER_TICKS_KEY)] = ticks
    health[('pps_gate', 'accepted_anchor_timestamp_ticks')] = ticks
    monkeypatch.setattr(module, '_read_csv', lambda path: [estimate])
    # Recovered status cannot release ARM before the full selected span.
    owner._startup_census_admitted = lambda: True
    owner._maybe_start_or_arm(health)
    assert owner.state['bench_attempt_arm_submission_count'] == 0
    estimate['source_acceptance_epoch'] = str(int(epoch) - 1)
    owner._maybe_qualify(health)
    assert owner.state['qualification_started_utc'] is None
    estimate['source_acceptance_epoch'] = epoch
    retained_frontier = owner.state['startup_reference_wait']['frontier_ticks']
    owner.state['startup_reference_wait']['frontier_ticks'] = int(ticks) - 599_000_000
    owner._maybe_qualify(health)
    assert owner.state['qualification_started_utc'] is None
    owner.state['startup_reference_wait']['frontier_ticks'] = retained_frontier
    owner._maybe_qualify(health)
    assert owner.state['qualification_started_utc'] is not None
    assert owner.state['startup_reference_wait']['resolved_utc'] is not None
    assert owner.state['qualified_acceptance_epoch_origin'] == int(epoch)
    assert owner.state['host_verification_hold'] is None
