# app/state_machine.py
from enum import Enum
from typing import Set, Dict

from app.models import BuildState

# Valid transitions: current -> {allowed next states}
TRANSITIONS: Dict[BuildState, Set[BuildState]] = {
    BuildState.QUEUED: {BuildState.PLANNING, BuildState.CANCELLED},
    BuildState.PLANNING: {BuildState.EXECUTING, BuildState.FAILED, BuildState.CANCELLED},
    BuildState.EXECUTING: {BuildState.REVIEWING, BuildState.WAITING_HUMAN, BuildState.FAILED, BuildState.CANCELLED},
    BuildState.REVIEWING: {BuildState.MERGING, BuildState.EXECUTING, BuildState.FAILED, BuildState.CANCELLED},
    BuildState.WAITING_HUMAN: {BuildState.EXECUTING, BuildState.CANCELLED},  # Resume or kill
    BuildState.MERGING: {BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED},
    BuildState.COMPLETED: set(),
    BuildState.FAILED: set(),
    BuildState.CANCELLED: set(),
}

def can_transition(current: BuildState, next_state: BuildState) -> bool:
    return next_state in TRANSITIONS.get(current, set())
