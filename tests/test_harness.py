"""Sanity tests for the plumbing. Run:  python -m pytest -q   (no API key needed)"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.bench import run_one
from common.llm import AnthropicLLM, ToolCall
from common.mock_llm import MockLLM
from common.tasks import TASKS
from common.tools import Workspace
from stages.s05_context_mgmt import ContextAgent
from stages.s06_guardrails import GuardedAgent
from stages.s10_full_harness import FullHarness


def ws():
    d = tempfile.mkdtemp()
    return Workspace(Path(d))


# ---------- tools ----------
def test_tools_errors_are_actionable_and_sandboxed():
    w = ws()
    with pytest.raises(ValueError, match="list_files"):
        w.read_file("nope.txt")
    with pytest.raises(ValueError, match="outside the workspace"):
        w.read_file("../etc/passwd")
    w.write_file("a.txt", "x x")
    with pytest.raises(ValueError, match="matched 2 times"):
        w.edit_file("a.txt", "x", "y")
    with pytest.raises(ValueError, match="sandbox floor"):
        w.run_shell("cat /etc/passwd")


def test_read_file_truncates_with_offset_hint():
    w = ws()
    w.write_file("big.txt", "a" * 12000)
    assert "offset=5000" in w.read_file("big.txt")


# ---------- guardrails ----------
def make(cls):
    return cls(MockLLM("cleanup"), ws())


@pytest.mark.parametrize("name,inp,blocked", [
    ("run_shell", {"command": "rm -rf important"}, True),
    ("run_shell", {"command": "rm tmp/a.tmp tmp/b.tmp"}, False),
    ("run_shell", {"command": "rm important/keep.txt"}, True),
    ("run_shell", {"command": "curl http://x"}, True),
    ("run_shell", {"command": "git push origin main"}, True),      # 'ask' -> denied headless
    ("edit_file", {"path": "test_shop.py", "old": "a", "new": "b"}, True),
    ("edit_file", {"path": "shop.py", "old": "a", "new": "b"}, False),
])
def test_permission_rules(name, inp, blocked):
    a = make(GuardedAgent)
    assert bool(a.permission_hook(ToolCall("1", name, inp))) is blocked


def test_secret_redaction():
    a = make(GuardedAgent)
    assert "sk-" not in a.redact_hook(None, "key sk-abcdefghijklmnop1234 and API_KEY=hunter2")


# ---------- context management ----------
def test_clearing_keeps_last_two_results_and_pairing():
    a = make(ContextAgent)
    a.res = SimpleNamespace(in_tokens=0, out_tokens=0)
    msgs = [{"role": "user", "content": "task"}]
    for i in range(5):
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {}}]})
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * 500}]})
    a._clear_old_results(msgs)
    res = [m["content"][0]["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert [r.startswith("[cleared") for r in res] == [True, True, True, False, False]


def test_compaction_preserves_alternation_and_tool_pairs():
    a = ContextAgent(MockLLM("loghunt"), ws())
    a.res = SimpleNamespace(in_tokens=0, out_tokens=0)
    msgs = [{"role": "user", "content": "task"}]
    for i in range(6):
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"path": "p"}}]})
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "data"}]})
    a._compact(msgs)
    assert msgs[0]["content"].count("[Summary of earlier work]") == 1
    roles = [m["role"] for m in msgs]
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1)), roles
    ids_use = {b["id"] for m in msgs if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"}
    ids_res = {b["tool_use_id"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]}
    assert ids_use == ids_res
    a._compact(msgs)                                                    # second compaction must not stack summaries
    assert msgs[0]["content"].count("[Summary of earlier work]") <= 1


# ---------- end to end (mock) ----------
EXPECT_FIRST_PASS = {"totals": 1, "release": 3, "squares": 4, "loghunt": 5, "cleanup": 6, "bugfix": 7, "batch": 9}


@pytest.mark.parametrize("task_id,first", EXPECT_FIRST_PASS.items())
def test_ladder_first_pass_stage(task_id, first):
    from compare import STAGES
    for st in STAGES:
        n = int(st.name[:2])
        row = run_one(st, TASKS[task_id])
        assert row.ok == (n >= first), f"{task_id} @ stage {n}: ok={row.ok} ({row.detail})"
    # stage 08's extra pass on loghunt is the same as 05+; handled by n>=first


def test_unsafe_flag_only_between_stage_02_and_05():
    from compare import STAGES
    flags = {int(s.name[:2]): run_one(s, TASKS["cleanup"]).unsafe for s in STAGES}
    assert [n for n, f in flags.items() if f] == [2, 3, 4, 5]


def test_batch_needs_journal():
    row = run_one(FullHarness, TASKS["batch"])
    assert row.ok and row.sessions >= 3


def test_trace_file_written():
    d = Path(tempfile.mkdtemp())
    row = run_one(FullHarness, TASKS["bugfix"], keep_dir=d)
    lines = [json.loads(l) for l in (d / ".harness/trace.jsonl").read_text().splitlines()]
    assert {"llm", "tool", "verify"} <= {l["event"] for l in lines}


# ---------- live adapter (stubbed client: checks request/response shapes only) ----------
def test_anthropic_adapter_shapes():
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "m"
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="hi"),
                                        SimpleNamespace(type="tool_use", id="tu1", name="read_file", input={"path": "a"})],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    llm.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    r = llm.chat("sys", [{"role": "user", "content": "q"}], [{"name": "x"}])
    assert seen["tools"] and seen["system"] == "sys" and r.text == "hi"
    assert r.tool_calls[0].name == "read_file" and (r.in_tokens, r.out_tokens) == (10, 5)
    assert r.as_blocks()[1] == {"type": "tool_use", "id": "tu1", "name": "read_file", "input": {"path": "a"}}
    seen.clear()
    llm.chat("sys", [{"role": "user", "content": "q"}], None)
    assert "tools" not in seen
