"""
STAGE 05 -- CONTEXT MANAGEMENT  (clear old tool results, then compact)
======================================================================
What's new : before EVERY model call the harness looks at the history and shrinks it.
             Two moves, cheapest first:
               1. TOOL-RESULT CLEARING - old tool outputs become a one-line stub
               2. COMPACTION           - if still big, summarise the middle with the model itself

In my words
-----------
The context window is working memory, and a loop re-sends the WHOLE history every turn.
Reading 12 log files = 12 big results sitting there forever, even though only the latest
one matters. Context engineering = keep the smallest set of high-signal tokens.

Trade-off I want to be able to say out loud: clearing is lossy. The agent can no longer
re-read what it cleared, so anything it must remember has to be in the plan (stage 04)
or a note (stage 09). That is why these stages are a stack, not alternatives.

Metric to watch: `loghunt` stops hitting `context_overflow`; compare `peak_ctx` vs stage 04.
Run it:   python -m stages.s05_context_mgmt --task loghunt -v
"""
from __future__ import annotations

from common.bench import cli
from common.llm import est_tokens
from common.runtime import CONTEXT_LIMIT
from stages.s04_planning import PlanningAgent

KEEP_LAST_RESULTS = 2          # how many most-recent tool results stay in full
COMPACT_AT = 0.70              # compact when history > 70% of the budget even after clearing
KEEP_TAIL_MESSAGES = 4         # compaction never touches the last few messages

COMPACT_SYSTEM = ("[COMPACT] You compress an agent's work log. Write a summary under 150 words that keeps: the goal, "
                  "what is DONE (files written, values found), what is still TODO, and any facts needed later. No fluff.")


class ContextAgent(PlanningAgent):
    name = "05 context mgmt"

    # ★ NEW: fills the `prepare` hook that stage 02 left empty
    def prepare(self, messages):
        super().prepare(messages)
        self._clear_old_results(messages)
        if est_tokens(messages) > COMPACT_AT * CONTEXT_LIMIT:
            self._compact(messages)

    # ---- move 1: clearing (free, lossy, no model call)
    def _clear_old_results(self, messages):
        blocks = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                  for b in m["content"] if b.get("type") == "tool_result"]
        for b in blocks[:-KEEP_LAST_RESULTS]:
            if not str(b["content"]).startswith("[cleared"):
                n = len(str(b["content"]))
                b["content"] = f"[cleared to save context: old tool result of {n} chars]"
                self.emit("clear", chars=n)

    # ---- move 2: compaction (costs one model call, keeps the gist)
    def _compact(self, messages):
        # cut point = an assistant message, so the kept tail still starts with a valid tool_use -> tool_result pair
        cut = max((i for i, m in enumerate(messages) if m["role"] == "assistant" and i <= len(messages) - KEEP_TAIL_MESSAGES),
                  default=0)
        if cut <= 1:
            return
        log = "\n".join(f"{m['role']}: {self._flat(m['content'])[:400]}" for m in messages[1:cut])
        r = self.llm.chat(COMPACT_SYSTEM, [{"role": "user", "content": log}], None)
        self.res.in_tokens += r.in_tokens
        self.res.out_tokens += r.out_tokens
        task = messages[0]["content"]
        task = task.split("\n\n[Summary of earlier work]")[0] if isinstance(task, str) else task
        messages[0] = {"role": "user", "content": f"{task}\n\n[Summary of earlier work]\n{r.text}"}
        del messages[1:cut]
        self.emit("compact", removed=cut - 1)

    @staticmethod
    def _flat(content) -> str:
        if isinstance(content, str):
            return content
        out = []
        for b in content:
            out.append(b.get("text") or (f"call {b['name']}({b['input']})" if b["type"] == "tool_use" else str(b.get("content", ""))))
        return " | ".join(out)


if __name__ == "__main__":
    cli(ContextAgent)
