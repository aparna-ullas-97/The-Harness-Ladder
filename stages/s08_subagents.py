"""
STAGE 08 -- SUBAGENTS  (context isolation)
==========================================
What's new : a `delegate` tool. The main agent hands a bounded job to a fresh agent with
             its OWN context window and a RESTRICTED toolset. Only a short answer comes back.

In my words
-----------
Stage 05 shrinks a context that is too big. Subagents stop it from growing in the first
place: the 12 log files get read inside the child's window and thrown away; the parent
only ever sees "svc_09.log, code E-4172".

What to say when asked "does it save tokens?": not necessarily TOTAL tokens (the child still
reads everything, plus a little overhead). It protects the parent's window and quality -
look at `peak_ctx` (parent) vs `total_tokens` (everyone). Honest trade-off, show both.

Design points: child gets read-only tools (least privilege), a turn cap, a size-capped
result, and cannot spawn its own children (no runaway recursion).

Metric to watch: `loghunt` parent `peak_ctx` drops sharply vs stage 07.
Run it:   python -m stages.s08_subagents --task loghunt -v
"""
from __future__ import annotations

from common.bench import cli
from common.tools import READ_ONLY_TOOLS
from stages.s05_context_mgmt import ContextAgent
from stages.s07_verification import VerifiedAgent

DELEGATE_SCHEMA = {
    "name": "delegate",
    "description": "Hand a self-contained research job to a helper agent with a fresh context and read-only file tools. "
                   "Use it when answering needs reading MANY files. You get back only its short answer.",
    "input_schema": {"type": "object", "properties": {"task": {"type": "string",
                     "description": "Complete instructions. The helper cannot see this conversation."}}, "required": ["task"]},
}

SUB_RULES = ("[SUBAGENT] You are a helper agent. You only have read-only tools. Do exactly the job given, "
             "then reply with a SHORT answer (under 60 words) containing only the facts asked for.")
SUB_RESULT_CAP = 1500


class SubagentAgent(VerifiedAgent):
    name = "08 subagents"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.register(DELEGATE_SCHEMA, self._delegate)           # ★ NEW tool

    def system_prompt(self, prompt):
        return super().system_prompt(prompt) + \
            "\n\nFor jobs that need reading many files, use `delegate` instead of reading them yourself."

    def _delegate(self, args: dict) -> str:
        task = args.get("task", "")
        if not task:
            raise ValueError("delegate needs a 'task' string with complete instructions.")
        # ★ child = a ContextAgent (stage 05): own window + clearing, but NO delegate tool, NO verification
        child = ContextAgent(self.llm, self.ws, turn_cap=15, verbose=self.verbose,
                             allowed=READ_ONLY_TOOLS, extra_system=SUB_RULES)
        r = child.run(task)
        self.res.absorb(r)                                       # parent pays for the child's tokens
        self.res.extra["sub_peak_ctx"] = max(self.res.extra.get("sub_peak_ctx", 0), r.peak_ctx)
        self.emit("delegate", task=task[:80], child_turns=r.turns, child_status=r.status, child_peak=r.peak_ctx)
        return (r.answer or f"(helper ended without an answer: {r.status})")[:SUB_RESULT_CAP]


if __name__ == "__main__":
    cli(SubagentAgent)
