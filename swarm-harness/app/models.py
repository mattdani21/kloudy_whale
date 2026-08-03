# app/models.py
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal
from datetime import datetime

class BuildState(Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    WAITING_HUMAN = "waiting_human"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AgentRole(Enum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    MERGER = "merger"
    TOOL = "tool"

class ModelProvider(Enum):
    DEEPSEEK = "deepseek"
    KIMI = "kimi"

@dataclass
class AgentConfig:
    role: AgentRole
    provider: ModelProvider
    model: str  # e.g., "deepseek-chat", "kimi-k3"
    temperature: float = 0.7
    max_tokens: int = 16384  # per-call output cap; deepseek-v4-flash reasons before answering, needs headroom
    system_prompt: str = ""
    token_budget: int = 20000

@dataclass
class Step:
    id: str
    agent_id: str
    role: AgentRole
    provider: ModelProvider
    prompt: str
    result: Optional[str] = None
    review: Optional[str] = None  # Cross-review output
    approved: bool = False
    tokens_used: int = 0
    duration_ms: float = 0.0
    retry_count: int = 0
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

@dataclass
class RepoConfig:
    """GitHub repo the build's files are written to (PAT stored per-build, never logged)."""
    owner: str
    name: str
    token: str
    branch: Optional[str] = None  # None -> default branch

@dataclass
class CreateRepoConfig:
    """Create a NEW GitHub repo under the PAT's owner before the build writes to it."""
    name: str
    token: str
    private: bool = True
    description: str = ""

@dataclass
class SwarmBuild:
    id: str
    prompt: str
    state: BuildState
    strategy: Literal["single", "swarm", "debate"] = "swarm"
    agents: List[AgentConfig] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    context: Dict = field(default_factory=dict)
    token_usage: int = 0
    token_budget_total: int = 4000000  # up to 4M tokens per build by default
    human_input_queue: List[Dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    final_output: Optional[str] = None
    error_log: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
