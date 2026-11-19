"""
STAGE 02 -- THE AGENT LOOP
==========================
What's new : `while not done: think -> act -> observe`. The model keeps going until it
             answers WITHOUT asking for a tool, or until a limit stops it.

In my words
-----------
This is the "agent" in agent. Everything else in this repo is a hook on this loop.
I made the hooks explicit (prepare / run_tool_call / on_finish / emit) so each later
stage is just "fill one hook". Read this file first, then every later file is a small diff.

Two limits live here, because a loop with no limits is a bill:
  * turn_cap        -> status "turn_cap"
  * context budget  -> status "context_overflow"  (the window filled up; nothing manages it yet!)

Metric to watch: `cleanup` now FAILS WITH UNSAFE=yes. More autonomy, zero safety = the
agent obeys the prompt-injection in NOTES.md and deletes important/. Stage 06 fixes that.
Run it:   python -m stages.s02_agent_loop --task bugfix -v
"""
from __future__ import annotations

import time

from common.bench import cli
from common.llm import est_tokens
from common.runtime import CONTEXT_LIMIT, RunResult
from stages.s01_tools import ToolAgent, result_block


class LoopAgent(ToolAgent):
    name = "02 agent loop"

    # ------------------------------------------------------------------ hooks (empty now)
    def prepare(self, messages: list[dict]) -> None:
        """Called before every model call. Stage 05 uses it to manage context."""

    def run_tool_call(self, call) -> tuple[str, bool]:
        """Called for every tool request. Stage 06 wraps it with permissions + hooks."""
        return self.dispatch(call)

    def on_finish(self, prompt: str, reply, messages: list[dict]) -> str | None:
        """Model wants to stop. Return None to accept, or a message to send it back to work.
        Stages 04 (open todos) and 07 (verification) use it."""
        return None

    def emit(self, event: str, **data) -> None:
        """Observability hook. Stage 10 writes these to a trace file."""

    # ------------------------------------------------------------------ the loop
    def run(self, prompt: str, session: int = 0) -> RunResult:
        res = self.res = RunResult()
        self.session = session
        system, tools = self.system_prompt(prompt), self.tool_schemas()
        messages = [{"role": "user", "content": prompt}]

        for turn in range(1, self.turn_cap + 1):
            self.turn = turn
            self.prepare(messages)

            ctx = est_tokens([system, tools, messages])
            res.peak_ctx = max(res.peak_ctx, ctx)
            if ctx > CONTEXT_LIMIT:                       # ★ the window is full
                res.status = "context_overflow"
                self.emit("overflow", ctx=ctx)
                break

            t0 = time.time()
            reply = self.llm.chat(system, messages, tools)  # ★ THINK
            res.in_tokens += reply.in_tokens
            res.out_tokens += reply.out_tokens
            res.turns = turn
            res.answer = reply.text or res.answer
            self.emit("llm", turn=turn, ctx=ctx, in_tokens=reply.in_tokens, out_tokens=reply.out_tokens,
                      tools=[c.name for c in reply.tool_calls], ms=int((time.time() - t0) * 1000))
            messages.append({"role": "assistant", "content": reply.as_blocks()})

            if not reply.tool_calls:                       # ★ model says "I'm done"
                feedback = self.on_finish(prompt, reply, messages)
                if feedback is None:
                    res.answer, res.status = reply.text, "finished"
                    break
                res.retries += 1
                self.say(f"harness> sent back to work: {feedback[:120]!r}")
                messages.append({"role": "user", "content": feedback})
                continue

            blocks = []
            for c in reply.tool_calls:                     # ★ ACT, then OBSERVE
                t1 = time.time()
                text, err = self.run_tool_call(c)
                res.tool_calls += 1
                self.say(f"tool> {c.name}({str(c.input)[:80]}) -> {text[:100]!r}")
                self.emit("tool", name=c.name, input=c.input, error=err, ms=int((time.time() - t1) * 1000))
                blocks.append(result_block(c, text, err))
            messages.append({"role": "user", "content": blocks})
        else:
            res.status = "turn_cap"
        self.messages = messages
        return res


if __name__ == "__main__":
    cli(LoopAgent)
