"""
common/bench.py -- runs one (stage, task) pair end-to-end and grades it; also the per-stage CLI.

Sessions: a task may allow several fresh sessions (`max_sessions`). Each session is a NEW agent object
(no Python state carried over) in the SAME workspace folder - exactly like a real restart. Only things
written to disk survive, which is what stage 09 is about.
"""
from __future__ import annotations

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common.runtime import RunResult
from common.tasks import TASKS, Task
from common.tools import Workspace


@dataclass
class Row:
    stage: str
    task: str
    ok: bool
    detail: str
    unsafe: bool
    res: RunResult
    sessions: int
    agent: object = None


def make_llm(live: bool, model: str | None, task_id: str):
    if live:
        from common.llm import AnthropicLLM
        return AnthropicLLM(model)
    from common.mock_llm import MockLLM
    return MockLLM(task_id)


def run_one(stage_cls, task: Task, live=False, model=None, verbose=False, keep_dir: Path | None = None) -> Row:
    tmp = None
    if keep_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="harness_")
        root = Path(tmp.name)
    else:
        root = keep_dir
    task.setup(root)
    llm = make_llm(live, model, task.id)

    total = RunResult()
    agent, sessions, last = None, 0, None
    for s in range(task.max_sessions):
        sessions += 1
        agent = stage_cls(llm, Workspace(root), turn_cap=task.turn_cap, acceptance_cmd=task.acceptance_cmd, verbose=verbose)
        if verbose:
            print(f"--- session {s} ({stage_cls.name}) ---")
        last = agent.run(task.prompt, session=s)
        total.absorb(last)
        total.turns += last.turns
        total.blocked += last.blocked
        total.retries += last.retries
        total.peak_ctx = max(total.peak_ctx, last.peak_ctx)
        total.extra.update(last.extra)
        if last.status in ("finished", "single_shot", "single_round", "context_overflow"):
            break                       # model stopped (or died) on its own; a new session would not help
    total.status = last.status
    total.answer = last.answer

    ok, detail, unsafe = task.check(root, total.answer)
    if tmp:
        tmp.cleanup()
    return Row(stage_cls.name, task.id, ok, detail, unsafe, total, sessions, agent)


def cli(stage_cls):
    ap = argparse.ArgumentParser(description=f"Run stage '{stage_cls.name}' on one task")
    ap.add_argument("--task", default="bugfix", choices=list(TASKS))
    ap.add_argument("--live", action="store_true", help="use the real Anthropic API (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--model", default=None, help="model id for --live (default: env HARNESS_MODEL or claude-sonnet-5-5)")
    ap.add_argument("--workdir", default=None, help="keep the workspace here (so you can open .harness/trace.jsonl afterwards)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    task = TASKS[a.task]
    print(f"[{'LIVE ' + (a.model or 'default model') if a.live else 'MOCK model (offline, scripted - tests plumbing, not intelligence)'}]")
    print(f"stage {stage_cls.name} | task {task.id}: {task.title}\n")
    keep = None
    if a.workdir:
        keep = Path(a.workdir)
        keep.mkdir(parents=True, exist_ok=True)
    row = run_one(stage_cls, task, a.live, a.model, verbose=True, keep_dir=keep)
    r = row.res
    print(f"\nresult : {'PASS' if row.ok else 'FAIL'}  ({row.detail})   unsafe={'YES' if row.unsafe else 'no'}")
    print(f"status : {r.status} | sessions {row.sessions} | turns {r.turns} | tool calls {r.tool_calls} | blocked {r.blocked} | retries {r.retries}")
    print(f"tokens : total {r.total_tokens} (in {r.in_tokens} / out {r.out_tokens}) | peak context {r.peak_ctx}")
    if hasattr(row.agent, "summary"):
        print("\n" + row.agent.summary())
