"""common/runtime.py -- shared result type + the (scaled-down) context budget."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# A real model has a 200k+ token window. To make "the window fills up" visible in a cheap
# benchmark, the harness enforces a small budget. Same mechanism, smaller number.
CONTEXT_LIMIT = int(os.getenv("HARNESS_CONTEXT_LIMIT", "6000"))


@dataclass
class RunResult:
    answer: str = ""
    status: str = ""          # single_shot | finished | turn_cap | context_overflow
    turns: int = 0
    tool_calls: int = 0
    blocked: int = 0          # tool calls refused by stage-06 policy
    retries: int = 0          # times stage-07 sent the agent back to work
    in_tokens: int = 0
    out_tokens: int = 0
    peak_ctx: int = 0         # largest context (est. tokens) the MAIN agent ever sent
    extra: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.in_tokens + self.out_tokens

    def absorb(self, other: "RunResult"):
        """Add another run's cost (used for subagents and multi-session runs)."""
        self.in_tokens += other.in_tokens
        self.out_tokens += other.out_tokens
        self.tool_calls += other.tool_calls
