"""
STAGE 07 -- VERIFICATION  (don't trust "I'm done")
==================================================
What's new : when the model says it is finished, the HARNESS checks, and can send it back.
             Two checkers, hard one first:
               1. ACCEPTANCE COMMAND - e.g. the project's test suite, run by the harness itself
               2. EVALUATOR          - a SEPARATE model call with a skeptical prompt, when no command exists

In my words
-----------
Models are bad judges of their own work - they grade it generously. Anthropic's finding in
"Harness design for long-running application development": tuning a *separate* evaluator to
be skeptical is far easier than making the generator critical of itself, and once that
outside feedback exists the generator has something concrete to fix.
Rule of thumb: if a deterministic check exists (tests, linter, schema), use it. Use an
LLM judge only for what code cannot check.

Cost: every retry is more tokens. `retries` and `total_tokens` columns show the price.
Cap retries - an evaluator that never says PASS is an infinite loop with an invoice.

Metric to watch: `bugfix` flips to PASS with retries >= 1 (model claimed done after fixing 1 of 2 bugs).
Run it:   python -m stages.s07_verification --task bugfix -v
"""
from __future__ import annotations

from common.bench import cli
from stages.s06_guardrails import GuardedAgent

MAX_VERIFY_RETRIES = 3

EVALUATOR_SYSTEM = """[EVALUATOR] You are a skeptical reviewer. A worker agent claims it finished a task.
Workers tend to over-rate their own work, so do not take the claim at face value.
Check every requirement in the task against the evidence (the final answer, the tool log, the workspace listing).
Reply with ONE first line, exactly 'VERDICT: PASS' or 'VERDICT: FAIL - <the specific requirement that is unmet>'."""


class VerifiedAgent(GuardedAgent):
    name = "07 verification"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.verify_attempts = 0

    # ★ NEW: stacks on top of stage 04's open-todo check (super() first = cheap check first)
    def on_finish(self, prompt, reply, messages):
        early = super().on_finish(prompt, reply, messages)
        if early:
            return early
        if self.verify_attempts >= MAX_VERIFY_RETRIES:
            return None                                   # give up gracefully; the status shows what happened
        self.verify_attempts += 1
        n = self.verify_attempts

        if self.acceptance_cmd and self.ws:               # 1. deterministic check
            ok, out = self.ws.check(self.acceptance_cmd)
            self.emit("verify", kind="command", ok=ok, attempt=n)
            if ok:
                return None
            return (f"ACCEPTANCE CHECK FAILED (attempt {n}/{MAX_VERIFY_RETRIES}) for `{self.acceptance_cmd}`:\n"
                    f"{out[-800:]}\nFix the cause, then finish again.")

        verdict = self._evaluate(prompt, reply, messages)  # 2. skeptical second opinion
        self.emit("verify", kind="evaluator", verdict=verdict[:80], attempt=n)
        if verdict.upper().startswith("VERDICT: PASS"):
            return None
        return f"REVIEW FAILED (attempt {n}/{MAX_VERIFY_RETRIES}): {verdict}\nAddress it, then finish again."

    def _evaluate(self, prompt, reply, messages) -> str:
        digest = []
        for m in messages:
            if m["role"] == "assistant":
                digest += [f"- {b['name']}({str(b['input'])[:90]})" for b in m["content"] if b["type"] == "tool_use"]
        evidence = (f"TASK:\n{prompt}\n\nFINAL ANSWER:\n{reply.text}\n\nTOOL LOG:\n" + "\n".join(digest[-25:]) +
                    f"\n\nWORKSPACE NOW:\n{self.ws.list_files('.') if self.ws else ''}")
        r = self.llm.chat(EVALUATOR_SYSTEM, [{"role": "user", "content": evidence}], None)
        self.res.in_tokens += r.in_tokens
        self.res.out_tokens += r.out_tokens
        return (r.text.strip().splitlines() or ["VERDICT: PASS"])[0]


if __name__ == "__main__":
    cli(VerifiedAgent)
