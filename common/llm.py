"""
common/llm.py  --  the ONLY place that talks to a model.

Everything in the harness sees one tiny interface:

    reply = llm.chat(system, messages, tools)

Messages use Anthropic's block format, so the same history works for the live API
and for the offline MockLLM:

    {"role": "user",      "content": "text"}
    {"role": "assistant", "content": [{"type":"text",...}, {"type":"tool_use","id","name","input"}]}
    {"role": "user",      "content": [{"type":"tool_result","tool_use_id","content","is_error"}]}
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    in_tokens: int = 0
    out_tokens: int = 0

    def as_blocks(self) -> list[dict]:
        """Assistant message content, ready to append to the history."""
        blocks: list[dict] = []
        if self.text:
            blocks.append({"type": "text", "text": self.text})
        for c in self.tool_calls:
            blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.input})
        return blocks or [{"type": "text", "text": ""}]


class AnthropicLLM:
    """Live model. Needs `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str | None = None):
        import anthropic  # imported lazily so mock mode needs no install

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("HARNESS_MODEL", "claude-sonnet-5-5")

    def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 2048) -> Reply:
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = self.client.messages.create(**kwargs)
        text, calls = [], []
        for b in resp.content:
            if b.type == "text":
                text.append(b.text)
            elif b.type == "tool_use":
                calls.append(ToolCall(b.id, b.name, dict(b.input)))
        return Reply("\n".join(text).strip(), calls, resp.usage.input_tokens, resp.usage.output_tokens)


def est_tokens(obj) -> int:
    """Cheap token estimate (~4 chars/token). Used for the context budget so runs are deterministic."""
    import json
    return len(json.dumps(obj, default=str)) // 4
