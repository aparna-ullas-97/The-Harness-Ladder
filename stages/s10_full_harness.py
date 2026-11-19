"""
STAGE 10 -- THE FULL HARNESS  (+ observability)
===============================================
What's new : TRACING. Every model call, tool call, block, clear, compaction, verification
             and delegation is written as one JSON line to .harness/trace.jsonl, and a
             readable summary is printed at the end.

In my words
-----------
You cannot improve what you cannot see. When an agent fails you need to answer: which turn,
which tool, how many tokens, what did the harness do about it? Tracing is also what makes the
benchmark trustworthy - the numbers in compare.py come from the same counters.

Everything below is inherited, so this file is tiny on purpose:

    10 FullHarness
     └ 09 persistence  (journal + notes across sessions)
        └ 08 subagents (context isolation)
           └ 07 verification (acceptance cmd / evaluator)
              └ 06 guardrails (permissions + hooks)
                 └ 05 context mgmt (clear + compact)
                    └ 04 planning (todo list, enforced)
                       └ 03 system prompt (assembled + AGENTS.md)
                          └ 02 agent loop (think -> act -> observe)
                             └ 01 tools (registry)  └ 00 bare model

Run it:   python -m stages.s10_full_harness --task bugfix -v
          python -m stages.s10_full_harness --task bugfix --live     # real model (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import json
import time
from collections import Counter

from common.bench import cli
from stages.s09_persistence import PersistentAgent


class FullHarness(PersistentAgent):
    name = "10 full harness"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events: list[dict] = []

    # ★ NEW: fills the `emit` hook from stage 02
    def emit(self, event: str, **data):
        rec = {"t": round(time.time(), 3), "session": getattr(self, "session", 0), "event": event, **data}
        self.events.append(rec)
        if self.dir:
            with open(self.dir / "trace.jsonl", "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")

    def summary(self) -> str:
        events = self.events
        if self.dir and (self.dir / "trace.jsonl").exists():          # whole run, all sessions
            events = [json.loads(l) for l in (self.dir / "trace.jsonl").read_text().splitlines()]
        c = Counter(e["event"] for e in events)
        llm_ms = sum(e.get("ms", 0) for e in events if e["event"] == "llm")
        tool_ms = sum(e.get("ms", 0) for e in events if e["event"] == "tool")
        rows = [f"{k:>12}: {v}" for k, v in sorted(c.items())]
        return "trace summary\n" + "\n".join(rows) + f"\n{'llm time':>12}: {llm_ms} ms\n{'tool time':>12}: {tool_ms} ms"


if __name__ == "__main__":
    cli(FullHarness)
