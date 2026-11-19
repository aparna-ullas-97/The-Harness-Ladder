"""
STAGE 01 -- TOOLS  (one round only)
===================================
What's new : a TOOL REGISTRY. The model can now ask for an action ("read this file",
             "run this python"); the harness executes it and hands back the result.

In my words
-----------
Tools turn the model from "talks about work" into "touches the world". But look at the
limit: we only do ONE round (ask -> run -> answer). Anything that needs a second look
("read the file, THEN edit it, THEN test") dies here. That gap is what stage 02 fixes.

Three tool-design rules (Anthropic, "Writing tools for agents") are visible in common/tools.py:
  1. few, clearly named tools, described like onboarding notes
  2. outputs are size-capped (a 1 MB file must not eat the context)
  3. errors say how to fix the call ("'old' matched 3 times - add more surrounding lines")

Metric to watch: `totals` flips from FAIL to PASS (the model can finally compute from real data).
Run it:   python -m stages.s01_tools --task totals -v
"""
from __future__ import annotations

from common.bench import cli
from common.llm import Reply, ToolCall
from common.runtime import RunResult
from common.tools import BASE_TOOLS, SCHEMAS, Workspace
from stages.s00_bare_model import BareModel


def result_block(call: ToolCall, text: str, is_error: bool) -> dict:
    return {"type": "tool_result", "tool_use_id": call.id, "content": text, "is_error": is_error}


class ToolAgent(BareModel):
    name = "01 tools"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # ★ NEW: the registry  name -> (schema the model sees, python function that runs it)
        self.tools = {}
        if self.ws is not None:
            for n in BASE_TOOLS:
                self.register(SCHEMAS[n], lambda args, n=n: self.ws.call(n, args))

    def register(self, schema: dict, handler):
        """Add a tool. Later stages (todo, delegate, note) plug in through here."""
        self.tools[schema["name"]] = (schema, handler)

    def tool_schemas(self) -> list[dict]:
        return [s for n, (s, _) in self.tools.items() if self.allowed is None or n in self.allowed]

    # ★ NEW: turn one model tool request into (result_text, is_error)
    def dispatch(self, call: ToolCall) -> tuple[str, bool]:
        if call.name not in self.tools or (self.allowed is not None and call.name not in self.allowed):
            return f"ERROR: unknown tool '{call.name}'. Available: {[s['name'] for s in self.tool_schemas()]}", True
        try:
            return self.tools[call.name][1](call.input), False
        except ValueError as e:          # fixable mistake: tell the model how
            return f"ERROR: {e}", True
        except Exception as e:           # anything else: still don't crash the harness
            return f"ERROR: {type(e).__name__}: {e}", True

    def run(self, prompt: str, session: int = 0) -> RunResult:
        res = RunResult(status="single_round")
        system, tools = self.system_prompt(prompt), self.tool_schemas()
        messages = [{"role": "user", "content": prompt}]

        r1 = self.llm.chat(system, messages, tools)
        res.in_tokens, res.out_tokens, res.turns = r1.in_tokens, r1.out_tokens, 1
        res.answer = r1.text
        if r1.tool_calls:
            messages.append({"role": "assistant", "content": r1.as_blocks()})
            out = []
            for c in r1.tool_calls:
                text, err = self.dispatch(c)
                self.say(f"tool> {c.name}({str(c.input)[:80]}) -> {text[:100]!r}")
                out.append(result_block(c, text, err))
                res.tool_calls += 1
            messages.append({"role": "user", "content": out})
            # ★ ONE more call to let the model read the results. If it asks for yet another
            #   tool we simply ignore it - there is no loop yet.
            r2 = self.llm.chat(system, messages, tools)
            res.in_tokens += r2.in_tokens
            res.out_tokens += r2.out_tokens
            res.turns = 2
            res.answer = r2.text
        self.say(f"model> {res.answer[:300]}")
        return res


if __name__ == "__main__":
    cli(ToolAgent)
