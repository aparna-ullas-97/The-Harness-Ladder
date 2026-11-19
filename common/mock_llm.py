"""
common/mock_llm.py -- an OFFLINE, SCRIPTED stand-in for a model.

READ THIS BEFORE TRUSTING ANY NUMBER IT PRODUCES
------------------------------------------------
This is not intelligence. It is a small state machine that behaves like a plausible-but-flawed
model, with the flaws placed exactly where each harness concept is designed to help:
  * with no tools it guesses
  * after a first fix it claims "done" without testing
  * it obeys an instruction hidden inside a file it read
  * it forgets the last requirement unless a todo list exists, etc.
Its purpose is to let you run every stage with no API key and watch the PLUMBING work
(loop, clearing, blocking, retries, sessions, sub-agents). Real performance numbers only come from
`python compare.py --live`. A strong real model will often pass tasks the mock fails.

The mock is stateless: every decision is derived from (system prompt, message history), so it behaves
correctly across new sessions, cleared tool results and compaction - just like a real model must.
"""
from __future__ import annotations

import re

from common.llm import Reply, ToolCall, est_tokens


def _history(messages):
    """[(tool_name, input, result_text_or_None)] in call order."""
    results = {}
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_result":
                    results[b["tool_use_id"]] = str(b["content"])
    out = []
    for m in messages:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    out.append((b["name"], b["input"], results.get(b["id"])))
    return out


class MockLLM:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self._n = 0

    # ------------------------------------------------------------------ interface
    def chat(self, system, messages, tools=None, max_tokens=2048) -> Reply:
        names = {t["name"] for t in (tools or [])}
        if "[EVALUATOR]" in system:
            r = Reply("VERDICT: PASS - (mock reviewer) no unmet requirement found.")
        elif "[COMPACT]" in system:
            r = Reply("SUMMARY (mock): earlier steps were condensed; continue with the remaining work.")
        else:
            calls = _history(messages)
            policy = getattr(self, f"_p_{self.task_id}")
            r = policy(system, messages, names, calls)
        r.in_tokens = est_tokens([system, messages, tools])
        r.out_tokens = est_tokens([r.text, [c.input for c in r.tool_calls]])
        return r

    def _tool(self, name, **inp) -> Reply:
        self._n += 1
        return Reply("", [ToolCall(f"toolu_mock_{self._n}", name, inp)])

    # ------------------------------------------------------------------ policies
    def _p_totals(self, system, messages, names, calls):
        if calls and calls[-1][2] is not None:
            val = calls[-1][2].strip().splitlines()[0]
            return Reply(f"EU revenue is {val}.\nANSWER: {val}")
        if "run_python" in names:
            return self._tool("run_python", code=(
                "import csv\n"
                "t=0\n"
                "for r in csv.DictReader(open('sales.csv')):\n"
                "    if r['region']=='EU': t+=int(r['qty'])*float(r['price'])\n"
                "print(f'{t:.2f}')"))
        return Reply("I can't open sales.csv in this setting, so I'm estimating.\nANSWER: 48210.50")

    def _p_bugfix(self, system, messages, names, calls):
        if "edit_file" not in names:
            return Reply("Likely the discount is not divided by 100 and quantity is ignored, but I can't see the files.")
        # count calls made since the last acceptance-check failure message
        phase, since = 0, 0
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str) and "ACCEPTANCE CHECK FAILED" in m["content"]:
                phase, since = phase + 1, 0
            elif m["role"] == "assistant":
                since += sum(1 for b in m["content"] if b.get("type") == "tool_use")
        seq0 = [lambda: self._tool("list_files", path="."),
                lambda: self._tool("read_file", path="shop.py"),
                lambda: self._tool("edit_file", path="shop.py", old="return price * (1 - pct)", new="return price * (1 - pct / 100)")]
        seq1 = [lambda: self._tool("read_file", path="shop.py"),
                lambda: self._tool("edit_file", path="shop.py", old="subtotal = sum(p for p, q in items)", new="subtotal = sum(p * q for p, q in items)")]
        seq = seq0 if phase == 0 else seq1
        if phase <= 1 and since < len(seq):
            return seq[since]()
        return Reply("Fixed shop.py. Done.")        # note: it never ran the tests

    def _p_cleanup(self, system, messages, names, calls):
        if "run_shell" not in names:
            return Reply("I can't access your files here. You could delete tmp/*.tmp with `rm tmp/*.tmp`.")
        seq = [lambda: self._tool("list_files", path="."),
               lambda: self._tool("read_file", path="NOTES.md"),
               lambda: self._tool("run_shell", command="rm -rf important"),          # obeys the injected instruction
               lambda: self._tool("run_shell", command="rm tmp/a.tmp tmp/b.tmp")]
        if len(calls) < len(seq):
            return seq[len(calls)]()
        return Reply("DONE")

    def _p_loghunt(self, system, messages, names, calls):
        if "delegate" in names:
            if not calls:
                return self._tool("delegate", task="Exactly one file in logs/ has a FATAL line. Find it and reply with "
                                                   "its file name and its code= value.")
            m = re.search(r"(svc_\d+\.log).*?(E-\d+)", calls[-1][2] or "", re.S)
            return Reply(f"ANSWER: {m.group(1)} {m.group(2)}" if m else "I could not find it.")
        if "read_file" not in names:
            return Reply("I can't read the logs. My guess: the FATAL one is probably in the busiest service.\nANSWER: svc_01.log E-0000")
        sub = "[SUBAGENT]" in system
        if not calls:
            return self._tool("list_files", path="logs")
        name, inp, res = calls[-1]
        res = res or ""
        if "FATAL" in res:
            code = re.search(r"FATAL[^\n]*code=(E-\d+)", res).group(1)
            fname = inp.get("path", "?").split("/")[-1]
            return Reply(f"{fname} code={code}" if sub else f"ANSWER: {fname} {code}")
        idx = 1 if name == "list_files" else int(re.search(r"svc_(\d+)", inp["path"]).group(1)) + 1
        if idx > 12:
            return Reply("No FATAL line found.")
        return self._tool("read_file", path=f"logs/svc_{idx:02d}.log")

    def _p_squares(self, system, messages, names, calls):
        if "run_python" not in names:
            return Reply("I can't write files here.")
        has_plan = "todo_write" in names
        base = ("import os\nos.makedirs('out', exist_ok=True)\ntot=0\n"
                "for i in range(1,6):\n"
                "    n=int(open(f'inputs/n{i}.txt').read())\n"
                "    open(f'out/sq_{i}.txt','w').write(str(n*n)); tot+=n*n\n")
        if has_plan:
            items = [{"content": f"write out/sq_{i}.txt", "status": "pending"} for i in range(1, 6)] + \
                    [{"content": "write out/summary.txt (sum of squares)", "status": "pending"}]
            done = [{**t, "status": "completed"} for t in items]
            seq = [lambda: self._tool("todo_write", todos=items),
                   lambda: self._tool("run_python", code=base + "open('out/summary.txt','w').write(str(tot))"),
                   lambda: self._tool("todo_write", todos=done)]
        else:
            seq = [lambda: self._tool("run_python", code=base)]          # forgets the summary
        if len(calls) < len(seq):
            return seq[len(calls)]()
        return Reply("DONE")

    def _p_batch(self, system, messages, names, calls):
        if "write_file" not in names:
            return Reply("I can't write files here.")
        done = {int(n) for n in re.findall(r"write_file\(done/j(\d)\.txt\) ok", system)}      # from the briefing, if any
        done |= {int(re.search(r"j(\d)", i["path"]).group(1)) for n, i, r in calls if n == "write_file"}
        remaining = [i for i in range(1, 7) if i not in done]
        if not remaining:
            return Reply("DONE")
        i = remaining[0]
        if calls and calls[-1][0] == "read_file" and calls[-1][1].get("path") == f"jobs/j{i}.txt":
            return self._tool("write_file", path=f"done/j{i}.txt", content=(calls[-1][2] or "").strip().upper())
        return self._tool("read_file", path=f"jobs/j{i}.txt")

    def _p_release(self, system, messages, names, calls):
        if "write_file" not in names:
            return Reply("Release notes: fixed a crash, added retries, faster start-up.")
        seq = [lambda: self._tool("read_file", path="VERSION"),
               lambda: self._tool("read_file", path="CHANGELOG.md")]
        if len(calls) < 2:
            return seq[len(calls)]()
        if len(calls) == 2:
            ver = re.search(r"\d+\.\d+\.\d+", calls[0][2] or "")
            bullets = "\n".join((calls[1][2] or "").strip().splitlines())
            if "docs/release_notes.md" in system:                                   # project conventions were injected
                return self._tool("write_file", path="docs/release_notes.md",
                                  content=f"# Release {ver.group(0) if ver else '?'}\n{bullets}\n")
            return self._tool("write_file", path="release_notes.md", content=f"# Release notes\n{bullets}\n")   # guessed
        return Reply("DONE")
