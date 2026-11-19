"""
STAGE 03 -- SYSTEM PROMPT ASSEMBLY + PROJECT CONTEXT
====================================================
What's new : the system prompt is no longer one fixed string. The harness BUILDS it each
             run from parts:   static rules  +  environment  +  project file (AGENTS.md)  +  tool guidance

In my words
-----------
The model starts every run knowing nothing about *your* project. Instead of hoping it goes
looking, the harness hands it the house rules up front. This is what CLAUDE.md / AGENTS.md
files are. Two details that matter in production:
  * static part first, dynamic part after -> the static prefix can be prompt-cached
  * every injected file has a character budget -> a huge rules file must not eat the window

Metric to watch: `release` flips to PASS (right path + right heading, taken from AGENTS.md).
Run it:   python -m stages.s03_system_prompt --task release -v
"""
from __future__ import annotations

import datetime

from common.bench import cli
from stages.s02_agent_loop import LoopAgent

STATIC_RULES = """You are an autonomous agent working inside a project workspace, using the tools provided.
Rules:
- Look before you act: list or read files before changing them.
- Prefer small, reversible steps. Never invent file contents or results - run a tool and read the output.
- When the task is complete, reply with the final answer and NO tool call.
- Follow the project conventions below exactly; they override your own habits."""

TOOL_GUIDANCE = """Tool tips: use run_python for counting/summing/parsing; read_file returns chunks of 5000 chars
(use the offset in the footer); errors tell you how to fix the call - read them."""

CONTEXT_FILE = "AGENTS.md"
CONTEXT_FILE_BUDGET = 2000     # chars; longer files are cut, never injected whole


class PromptedAgent(LoopAgent):
    name = "03 system prompt"

    # ★ NEW: assemble, don't hard-code. Order = most stable first (cache-friendly).
    def system_prompt(self, prompt: str) -> str:
        parts = [STATIC_RULES, TOOL_GUIDANCE]            # static: identical on every run
        parts.append(self.environment())                 # dynamic from here on
        ctx = self.project_context()
        if ctx:
            parts.append(ctx)
        if self.extra_system:
            parts.append(self.extra_system)
        return "\n\n".join(parts)

    def environment(self) -> str:
        top = self.ws.list_files(".") if self.ws else "(no workspace)"
        return f"# Environment\nDate: {datetime.date.today()}\nWorkspace top level:\n{top}"

    def project_context(self) -> str:
        if not self.ws:
            return ""
        p = self.ws.root / CONTEXT_FILE
        if not p.is_file():
            return ""
        text = p.read_text()
        if len(text) > CONTEXT_FILE_BUDGET:
            text = text[:CONTEXT_FILE_BUDGET] + "\n[project file cut at budget]"
        return f"# Project conventions (from {CONTEXT_FILE})\n{text}"


if __name__ == "__main__":
    cli(PromptedAgent)
