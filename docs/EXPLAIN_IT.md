# Explain it: 30-second versions and likely questions

## The whole thing in 30 seconds
"A model on its own just answers. A harness is the code around it that lets it *work*: a loop so it can take many steps,
tools so it can touch real data, rules so it cannot do damage, checks so 'done' means done, and memory that lives
outside the context window. I built it as 11 files. Each file adds one concept. A benchmark runs all 11 on the same
7 tasks, so I can show what each concept actually buys."

## One line per stage (what to say)
| Stage | Say this |
|---|---|
| 00 | "Brain in a jar. It can talk about your files, not open them." |
| 01 | "Tools: the model asks, the harness executes. One round only, so multi-step work still fails." |
| 02 | "The loop: think, act, observe, repeat. This is the agent. Cost jumps ~5x because history is re-sent every turn." |
| 03 | "The harness builds the system prompt and injects the project's `AGENTS.md`, so the model knows the house rules." |
| 04 | "A todo list the harness enforces. If items are open when the model says done, it gets sent back." |
| 05 | "Context is a budget. Clear old tool results first (free, lossy), compact with a summary if still big." |
| 06 | "Model proposes, harness disposes. Rules + hooks. Defends against prompt injection." |
| 07 | "Don't trust 'done'. Run the tests, or ask a separate skeptical reviewer. Cap the retries." |
| 08 | "Subagents: fresh window, read-only tools, short answer back. Protects the parent's context, not total tokens." |
| 09 | "Journal + notes on disk, injected into the next session. The window is not memory." |
| 10 | "Trace everything as JSON lines, so a failure can be located by turn, tool and token count." |

## Questions you will get
**Q: What is the difference between a harness and a framework like LangGraph?**
A framework gives you building blocks (graphs, state, checkpoints). A harness is the specific design on top: which
tools, what context policy, which rules, which checks. This repo has no framework; the loop is ~40 lines, which is the point.

**Q: Why not just use a bigger context window?**
Loops re-send the whole history every turn, so cost and latency grow with it, and quality can degrade as the window
fills. Anthropic also reports models wrapping up early as the window fills ("context anxiety"). Bigger windows help;
managing what is in them still matters.

**Q: Compaction vs clearing vs subagents vs notes. When which?**
| Move | Cost | Loses | Use when |
|---|---|---|---|
| Clear old tool results | free | exact old outputs | results are big and only the latest matters |
| Compact (summary) | 1 model call | detail | one long session, continuity matters |
| Subagent | extra tokens | nothing in the parent (child's detail is gone) | bounded search/read job |
| Notes / journal | tiny | nothing, if written | anything needed after clearing or in a new session |

**Q: Why verify with a separate evaluator instead of asking the model to double-check?**
Models grade their own work generously. A separate, skeptical evaluator is easier to tune than making the generator
self-critical (Anthropic, harness-design post). If a deterministic check exists (tests), use that instead; it is cheaper and cannot be talked round.

**Q: How do you defend against prompt injection?**
Treat everything the model reads as data, not instructions, and enforce limits in code, outside the model. Stage 06
blocks `rm -rf` even when a file the agent read asked for it. Limit: rules reduce mistakes, they are not an OS sandbox.

**Q: Does a harness still matter as models get better?**
Yes, but the shape changes. Each part encodes an assumption about what the model cannot do alone; some become
unnecessary. Re-test on every model change and remove what stopped helping.

**Q: Does it save money?**
Autonomy costs: stage 01 → 02 is about 5x tokens in the mock run. Subagents and verification add tokens too. You pay
for reliability and safety, and you should measure it (`tokens` column).

**Q: What would you build next?**
In this order: run `--live` and publish the real table; MCP tool handler; a skills loader; container sandbox;
more tasks with repeats so differences are statistically meaningful.

## 5-minute demo script
1. `python compare.py` → point at the table: passes climb, `unsafe` appears at 02 and vanishes at 06.
2. `python -m stages.s02_agent_loop --task cleanup -v` → watch it run `rm -rf important`.
3. `python -m stages.s06_guardrails --task cleanup -v` → same task, `BLOCKED by policy`, agent adapts.
4. `python -m stages.s07_verification --task bugfix -v` → "done" gets rejected once, then fixed.
5. `python -m stages.s10_full_harness --task batch --workdir /tmp/demo` → three sessions, progress carried by the journal; open `.harness/trace.jsonl`.
