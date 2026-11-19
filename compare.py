"""
compare.py -- run every stage on every task and print the ladder table.

    python compare.py                      # offline mock model (tests plumbing; NOT a performance claim)
    python compare.py --live               # real model (needs ANTHROPIC_API_KEY); costs money
    python compare.py --live --model claude-haiku-5-5 --repeat 3    # weaker model shows bigger gaps; repeat to average noise
    python compare.py --stages 2 5 10 --tasks bugfix loghunt

Columns: PASS rate per task, then cost columns summed over all tasks.
"""
from __future__ import annotations

import argparse

from common.bench import run_one
from common.tasks import TASKS
from stages.s00_bare_model import BareModel
from stages.s01_tools import ToolAgent
from stages.s02_agent_loop import LoopAgent
from stages.s03_system_prompt import PromptedAgent
from stages.s04_planning import PlanningAgent
from stages.s05_context_mgmt import ContextAgent
from stages.s06_guardrails import GuardedAgent
from stages.s07_verification import VerifiedAgent
from stages.s08_subagents import SubagentAgent
from stages.s09_persistence import PersistentAgent
from stages.s10_full_harness import FullHarness

STAGES = [BareModel, ToolAgent, LoopAgent, PromptedAgent, PlanningAgent, ContextAgent,
          GuardedAgent, VerifiedAgent, SubagentAgent, PersistentAgent, FullHarness]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--repeat", type=int, default=1, help="runs per cell (live mode is noisy; use 3+)")
    ap.add_argument("--stages", type=int, nargs="*", help="stage numbers to run, e.g. 0 2 10")
    ap.add_argument("--tasks", nargs="*", choices=list(TASKS))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    stages = [s for s in STAGES if a.stages is None or int(s.name[:2]) in a.stages]
    tasks = [TASKS[t] for t in (a.tasks or TASKS)]
    mode = f"LIVE ({a.model or 'default model'})" if a.live else "MOCK (scripted offline stand-in - proves the plumbing, NOT model quality)"
    print(f"mode: {mode} | repeat: {a.repeat}\n")

    head = f"{'stage':<18}" + "".join(f"{t.id:>9}" for t in tasks) + f"{'PASS':>7}{'tokens':>9}{'peakctx':>9}{'blocked':>8}{'retries':>8}{'UNSAFE':>7}"
    print(head)
    print("-" * len(head))
    for st in stages:
        cells, tot_tok, peak, blocked, retries, unsafe, passed = [], 0, 0, 0, 0, 0, 0
        for t in tasks:
            ok_n = 0
            for _ in range(a.repeat):
                row = run_one(st, t, a.live, a.model, a.verbose)
                ok_n += row.ok
                tot_tok += row.res.total_tokens
                peak = max(peak, row.res.peak_ctx) if t.id == "loghunt" else peak
                blocked += row.res.blocked
                retries += row.res.retries
                unsafe += row.unsafe
            passed += ok_n
            cells.append(f"{ok_n}/{a.repeat}" if a.repeat > 1 else ("PASS" if ok_n else "fail"))
        n = len(tasks) * a.repeat
        print(f"{st.name:<18}" + "".join(f"{c:>9}" for c in cells) +
              f"{passed:>4}/{n:<2}{tot_tok // a.repeat:>9}{peak:>9}{blocked // a.repeat:>8}{retries // a.repeat:>8}{unsafe:>7}")
    print("\npeakctx = largest context (est. tokens) on the loghunt task; context budget is HARNESS_CONTEXT_LIMIT (default 6000).")
    print("tokens = average total (input+output, incl. subagents and evaluator) across all tasks per repeat.")


if __name__ == "__main__":
    main()
