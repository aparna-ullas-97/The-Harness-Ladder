# Concepts: what a harness is made of (researched Nov 2026)

## How I decided what is "important"
I searched for current engineering writing on agent harnesses and cross-checked the list against how Anthropic
describes its own harness work. A concept made the cut if (a) it shows up in several independent sources and
(b) I could build it small enough to measure on a task. Everything else is listed in section 3.

Primary sources I opened in full: the three Anthropic engineering posts marked ★. The rest I read through search excerpts only, so treat their claims as pointers.

| Source | Used for |
|---|---|
| ★ Anthropic, *Effective harnesses for long-running agents* (Nov 26, 2025) | persistence, handoff artifacts, premature completion, untested success |
| ★ Anthropic, *Harness design for long-running application development* (Mar 24, 2026) | evaluator/generator split, context anxiety, compaction vs resets, "simplify as models improve" |
| ★ Anthropic, *Writing effective tools for agents — with agents* (Sep 11, 2025) | tool design rules |
| Arize, *What is an agent harness?* | the "nine components" framing (loop, context mgmt, tools & skills, subagents, session persistence, system prompt assembly, lifecycle hooks, permissions, built-in skills) |
| Anthropic context-engineering write-up, via the agentic-ai.readthedocs.io summary | clear / compact / note-taking / isolate |

## 1. The 10 concepts I built (and where)

| # | Concept | What it solves | Failure it prevents | Stage |
|---|---|---|---|---|
| 1 | Tools (agent-computer interface) | model cannot touch data | guessing | 01 |
| 2 | Agent loop | one round is not enough | stopping after step 1 | 02 |
| 3 | System prompt assembly + project context | model knows nothing about *your* project | wrong paths, wrong formats | 03 |
| 4 | Planning / todo | long tasks drift | silently dropped requirement | 04 |
| 5 | Context management (clear, compact) | window fills, quality degrades | overflow, "context rot" | 05 |
| 6 | Permissions + lifecycle hooks | model is not a security boundary | prompt injection, destructive commands | 06 |
| 7 | Verification (command / evaluator) | models over-rate their own work | "done" that is not done | 07 |
| 8 | Subagents | context grows in the first place | parent window polluted by search noise | 08 |
| 9 | Persistence / handoff | each session starts blank | redoing or abandoning work | 09 |
| 10 | Observability (trace) | cannot debug what you cannot see | mystery failures | 10 |

### Tool design rules (Anthropic, writing-tools post) and where they show up in code
| Rule | In this repo |
|---|---|
| Few, well-chosen tools; avoid overlap | 6 base tools, each with one job (`common/tools.py`) |
| Return meaningful context, concise by default | `list_files` shows names + sizes, not raw metadata |
| Token efficiency: truncate with sensible defaults and say how to narrow | `read_file` caps at 5,000 chars and the footer gives the next `offset` |
| Helpful, actionable errors | `edit_file`: "matched 3 times… add surrounding lines" |
| Describe tools like onboarding a new teammate | schema descriptions in `SCHEMAS` |

### What Anthropic's long-running setup does vs my stage 09
| Anthropic (effective-harnesses post) | Mine |
|---|---|
| Initializer agent sets up the environment in session 1 | not built |
| `feature_list.json`, all items start failing; coder may only flip `passes` | covered loosely by todo (04) + verification (07) |
| `claude-progress.txt` log of each session | `.harness/journal.md` (automatic) + `notes.md` (agent-written) |
| Git commits after each change | not built |
| Session start: `pwd`, read git log + progress file, pick next feature | journal injected into the system prompt |
| Browser end-to-end testing | acceptance command / evaluator in 07 |

### Compaction vs context reset (harness-design post)
- **Compaction**: summarise in place, same agent continues. Keeps continuity, but the agent gets no clean slate.
- **Context reset**: fresh agent + structured handoff. Clean slate, but orchestration overhead and the handoff must carry enough state.
- This repo: stage 05 = compaction (+ clearing). A new session in stage 09 = a reset with a handoff.
- The post names **context anxiety** (model wraps up early as the window fills) as the reason resets matter for some models. I did not build a test for it.

## 2. Principle that ties it together
> Every component of a harness encodes an assumption about what the model can't do on its own, and those assumptions can go stale. Find the simplest solution possible; add complexity only when needed. (Anthropic, harness-design post, paraphrased)

Practical use: re-run `compare.py --live` whenever you switch models, and delete the stages that stopped moving the table.

## 3. Important today, NOT built here
| Concept | Why it matters | Where it would plug in |
|---|---|---|
| MCP (standard tool/server protocol) | tools from outside your code, shared across agents | `register(schema, handler)` in stage 01; a handler that forwards to an MCP server |
| Skills (instructions loaded on demand) | keeps the system prompt small; progressive disclosure | a `load_skill` tool + a folder of `SKILL.md` files, between 03 and 04 |
| Long-term memory store (across projects/users) | persistence beyond one workspace | replace the journal file with a store; keep the same inject-at-start pattern |
| Real sandbox (container, network policy) | rules are not an OS boundary | wrap `Workspace._run` |
| Planner → generator → evaluator multi-agent builds | long, subjective tasks (e.g. UI) | stage 07's evaluator promoted to a full agent with browser tools |
| Prompt caching, streaming, retries/backoff, rate limits | cost, latency, reliability | inside `AnthropicLLM.chat` |
| Human-in-the-loop approval UI | the "ask" decision in 06 | implement `GuardedAgent.approve` |
| Real eval suites with many tasks and repeats | decisions need statistics | grow `common/tasks.py`; `--repeat` already averages |
