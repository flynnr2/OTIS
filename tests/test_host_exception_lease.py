import ast
import inspect
import time
from copy import deepcopy

import pytest

from host.otis_tools import adaptive_hybrid_supervisor as module
from host.otis_tools.adaptive_hybrid_contract import UNATTENDED_72_HOUR_HYBRID_CONTROL
from tests.runtime_fixtures import construct_simulated_supervisor


def test_every_supervisor_self_method_call_resolves_across_inheritance():
    cls = module.AdaptiveHybridSupervisor
    missing = set()
    for parent in cls.__mro__:
        if parent is object:
            continue
        for node in ast.walk(ast.parse(inspect.getsource(parent))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self'
                and not callable(getattr(cls, node.func.attr, None))):
                missing.add(f'{parent.__name__}.{node.func.attr}')
    assert not missing


def test_expired_evidence_deadline_cannot_disable_admitted_hold_lease(tmp_path, monkeypatch):
    owner = construct_simulated_supervisor(tmp_path, purpose=UNATTENDED_72_HOUR_HYBRID_CONTROL)
    owner._startup_census_admitted = lambda: True
    owner._check_capture_transport_state = lambda: None
    owner._save = lambda: None
    owner._live_command_ack_required = False
    owner.state['startup_census_process_nonce'] = 1
    owner.state['host_verification_hold'] = {'error': 'pending review'}
    owner.state['inflight_evidence_acknowledgement'] = {
        'causal_observation_owner_nonce': 1,
        'causal_observation_deadline_monotonic_ns': time.monotonic_ns() - 1,
    }
    retained = deepcopy(owner.state['inflight_evidence_acknowledgement'])
    commands = []
    monkeypatch.setattr(module.AdaptiveHybridSupervisorBase, '_command', lambda self, command: commands.append(command))
    owner._last_lease_monotonic_ns = None
    owner._service_capture_lease()
    assert len(commands) == 1 and commands[0].startswith('ACTIVE LEASE ')
    assert owner.state['inflight_evidence_acknowledgement'] == retained
    with pytest.raises(TimeoutError):
        owner._command('ACTIVE SNAPSHOT 1')
    owner._normal_command_ack_pending = True
    with pytest.raises(ValueError, match='acknowledgement is unresolved'):
        owner._renew_lease()
    assert len(commands) == 1


def test_post_origin_fault_enters_review_without_retired_recovery_call(tmp_path):
    from tests.test_startup_reference_wait import subject
    owner, health = subject(tmp_path)
    owner.state.update(qualified_origin_session_id=1,
                       qualified_acceptance_epoch_origin=1,
                       qualified_authoritative_capture_baseline={
                           key: 0 for key in module._authoritative_capture_counters(owner.programme)
                       })
    assert owner._abort_on_authoritative_capture_discontinuity(health)
    assert owner.state['host_verification_hold']['source'] == 'authoritative_capture_observer'
    assert owner.state['terminal'] is None


def test_foreground_fallback_services_existing_lease(tmp_path, monkeypatch):
    from host.otis_tools import live_run
    from tests.test_live_run import _ReviewCapture
    capture = _ReviewCapture(None, None, 7)
    class Owner:
        renewals = 0
        def _enter_host_verification_hold(self, error, *, source):
            pass
        def _service_capture_lease(self):
            self.renewals += 1
    owner = Owner()
    monkeypatch.setattr(live_run, 'read_capture_transport_state', lambda *a, **k: {
        'emergency_abort_latched': False, 'emergency_aborts_sent': 0})
    monkeypatch.setattr(live_run.time, 'sleep', lambda seconds: None)
    result = live_run._retain_foreground_review_hold(
        run_dir=tmp_path, device='/dev/fake', capture=capture, supervisor=owner,
        error=AttributeError('retained unexpected exception'))
    assert owner.renewals == 2
    assert result['status'] == 'pending_review_capture_ended'
