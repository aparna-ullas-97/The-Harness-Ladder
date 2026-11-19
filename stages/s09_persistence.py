"""
STAGE 09 -- PERSISTENCE  (progress that survives the session)
==============================================================
What's new : a JOURNAL the harness writes after every tool call, a `save_note` tool for
             the agent's own handoff notes, and both are injected into the NEXT session's prompt.

In my words
-----------
Real tasks outlive one context window (or one crash, or one night). Each new session starts
with zero memory - Anthropic's picture is engineers working in shifts, each arriving with no
idea what the last shift did. The fix is not a bigger window, it is a HANDOFF ARTIFACT that
lives outside the window: a progress file (plus, in their coding setup, a feature list and git commits).
Compaction alone is not enough because it only stretches ONE session.

Two kinds of memory, keep them apart:
  * journal  = facts the harness recorded (reliable, automatic, can't be forgotten)
  * notes    = what the agent chose to write down (judgement, can be wrong)
Writing every thought into long-term memory is how one bad assumption poisons all future sessions,
so the journal stays mechanical and notes stay few.

Metric to watch: `batch` (turn cap 5 per session, needs 3 sessions) flips from FAIL to PASS.
Run it:   python -m stages.s09_persistence --task batch -v
"""
from __future__ import annotations

from common.bench import cli
from stages.s08_subagents import SubagentAgent

NOTE_SCHEMA = {
    "name": "save_note",
    "description": "Save a short handoff note for your future self (decisions, gotchas, what to do next). "
                   "Keep it to one or two lines. Facts about finished work are recorded automatically; do not repeat them.",
    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
}
JOURNAL_LINES_IN_PROMPT = 40


class PersistentAgent(SubagentAgent):
    name = "09 persistence"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.dir = (self.ws.root / ".harness") if self.ws else None
        if self.dir:
            self.dir.mkdir(exist_ok=True)
            self.register(NOTE_SCHEMA, self._save_note)             # ★ NEW tool

    # ---- write side
    def run_tool_call(self, call):
        text, err = super().run_tool_call(call)
        if self.dir and call.name != "save_note":                  # ★ harness records, the model can't forget
            arg = call.input.get("path") or call.input.get("command") or call.input.get("task") or ""
            status = "ERROR" if err else "ok"
            with open(self.dir / "journal.md", "a") as f:
                f.write(f"- [s{getattr(self, 'session', 0)} t{getattr(self, 'turn', 0)}] {call.name}({str(arg)[:70]}) {status}\n")
        return text, err

    def _save_note(self, args: dict) -> str:
        text = str(args.get("text", "")).strip()[:300]
        if not text:
            raise ValueError("save_note needs a non-empty 'text'.")
        with open(self.dir / "notes.md", "a") as f:
            f.write(f"- {text}\n")
        return "note saved"

    # ---- read side: the next session starts already briefed
    def system_prompt(self, prompt):
        base = super().system_prompt(prompt)
        if not self.dir:
            return base
        journal = self._tail(self.dir / "journal.md", JOURNAL_LINES_IN_PROMPT)
        notes = self._tail(self.dir / "notes.md", 20)
        if not journal and not notes:
            return base
        brief = ["# Progress from earlier sessions (read first; do NOT redo finished work)"]
        if journal:
            brief.append("Journal (automatic):\n" + journal)
        if notes:
            brief.append("Your notes:\n" + notes)
        return base + "\n\n" + "\n".join(brief)

    @staticmethod
    def _tail(path, n: int) -> str:
        return "\n".join(path.read_text().splitlines()[-n:]) if path.exists() else ""


if __name__ == "__main__":
    cli(PersistentAgent)
