from app.models import BuildState
from app.state_machine import TRANSITIONS, can_transition

def test_happy_path():
    assert can_transition(BuildState.QUEUED, BuildState.PLANNING)
    assert can_transition(BuildState.PLANNING, BuildState.EXECUTING)
    assert can_transition(BuildState.EXECUTING, BuildState.REVIEWING)
    assert can_transition(BuildState.REVIEWING, BuildState.MERGING)
    assert can_transition(BuildState.MERGING, BuildState.COMPLETED)

def test_invalid_transitions_rejected():
    assert not can_transition(BuildState.QUEUED, BuildState.EXECUTING)
    assert not can_transition(BuildState.QUEUED, BuildState.COMPLETED)
    assert not can_transition(BuildState.PLANNING, BuildState.MERGING)
    assert not can_transition(BuildState.MERGING, BuildState.EXECUTING)

def test_human_gate_cycle():
    assert can_transition(BuildState.EXECUTING, BuildState.WAITING_HUMAN)
    assert can_transition(BuildState.WAITING_HUMAN, BuildState.EXECUTING)
    assert can_transition(BuildState.WAITING_HUMAN, BuildState.CANCELLED)
    assert not can_transition(BuildState.WAITING_HUMAN, BuildState.COMPLETED)

def test_terminal_states_have_no_exits():
    for terminal in (BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED):
        assert TRANSITIONS[terminal] == set()
        for other in BuildState:
            assert not can_transition(terminal, other)

def test_cancellable_from_non_terminal_states():
    for state in (BuildState.QUEUED, BuildState.PLANNING, BuildState.EXECUTING,
                  BuildState.REVIEWING, BuildState.WAITING_HUMAN, BuildState.MERGING):
        assert can_transition(state, BuildState.CANCELLED)

def test_every_state_has_an_entry():
    for state in BuildState:
        assert state in TRANSITIONS
