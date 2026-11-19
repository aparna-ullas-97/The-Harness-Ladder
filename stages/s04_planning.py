"""
STAGE 04 -- PLANNING  (an explicit todo list the agent must keep honest)
========================================================================
What's new : a `todo_write` tool + a harness rule: the agent may not finish while todos are open.

In my words
-----------
Long tasks fail by DRIFT: the model does steps 1-5 and quietly forgets step 6.
A todo list fixes this two ways:
  1. it forces the model to write the full scope down once (structured note-taking)
  2. the harness can CHECK it - if todos are still open when the model says "done",
     we push back. The plan is not just a hint, it is something enforceable.

This is the first `on_finish` hook in use. Notice we call super() so later stages can stack checks.

Metric to watch: `squares` flips to PASS (the 6th output - summary.txt - no longer gets dropped).
Run it:   python -m stages.s04_planning --task squares -v
"""
from __future__ import annotations

from common.bench import cli
from stages.s03_system_prompt import PromptedAgent

TODO_SCHEMA = {
    "name": "todo_write",
    "description": "Write or update your task list. Send the FULL list each time. Use it at the start of any task with "
                   "3+ steps, and mark items completed as you finish them. Exactly one item should be in_progress.",
    "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "items": {
        "type": "object",
        "properties": {"content": {"type": "string"},
                       "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
        "required": ["content", "status"]}}}, "required": ["todos"]},
}

PLANNING_GUIDANCE = ("For any task with 3 or more steps, FIRST call todo_write with every requirement from the task, "
                     "then work through them and keep the list updated. Do not reply 'done' while items are open.")


class PlanningAgent(PromptedAgent):
    name = "04 planning"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.todos: list[dict] = []
        self.nudges = 0
        self.register(TODO_SCHEMA, self._todo_write)             # ★ NEW tool

    def system_prompt(self, prompt: str) -> str:
        return super().system_prompt(prompt) + "\n\n" + PLANNING_GUIDANCE

    def _todo_write(self, args: dict) -> str:
        todos = args.get("todos")
        if not isinstance(todos, list) or not all(isinstance(t, dict) and "content" in t and "status" in t for t in todos):
            raise ValueError("todos must be a list of {content, status} objects.")
        self.todos = todos
        return "Todo list saved:\n" + "\n".join(f"[{t['status']}] {t['content']}" for t in todos)

    # ★ NEW: the harness enforces the plan
    def on_finish(self, prompt, reply, messages):
        open_items = [t["content"] for t in self.todos if t["status"] != "completed"]
        if open_items and self.nudges < 2:
            self.nudges += 1
            self.emit("todo_nudge", open=open_items)
            return "You still have unfinished todos: " + "; ".join(open_items) + \
                   ". Finish them, or update the list if they are no longer needed, before replying."
        return super().on_finish(prompt, reply, messages)


if __name__ == "__main__":
    cli(PlanningAgent)
