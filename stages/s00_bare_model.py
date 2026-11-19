"""
STAGE 00 -- THE BARE MODEL
==========================
What it is : send in one prompt, and it give an answer. theres no tools, no loop or memory
What's new : This is the baseline everything else is measured against.

This model is a brain in a jar. It can talk about your files but it cannot open them.
Any task that needs *real data or real actions* is a guess here.

Run it:   python -m stages.s00_bare_model --task totals
"""
from __future__ import annotations

from common.bench import cli
from common.runtime import RunResult

#agent implementation
class BareModel:
    name = "00 bare model"

    #stores references
    def __init__(self, llm, ws=None, turn_cap=12, acceptance_cmd=None, verbose=False,
                 allowed=None, extra_system=""):
        #the language model client and the workspace
        self.llm, self.ws = llm, ws
        self.turn_cap, self.acceptance_cmd, self.verbose = turn_cap, acceptance_cmd, verbose
        self.allowed, self.extra_system = allowed, extra_system

    def system_prompt(self, prompt: str) -> str:
        return "You are a helpful assistant."

    #lightweight logger
    def say(self, msg: str):
        if self.verbose:
            print(msg)

    # core logic: calls llm chat with system prompt and single user message, no tools
    # logs out first 300 chars of the reply
    # return RunResult (dataclass in runtime.py, a standard return value for run() method)
        # answer: llm response
        #status (single_shot, finishes, turn_cap, context_overflow)
    def run(self, prompt: str, session: int = 0) -> RunResult:
        reply = self.llm.chat(self.system_prompt(prompt), [{"role": "user", "content": prompt}], tools=None)
        self.say(f"model> {reply.text[:300]}")
        return RunResult(answer=reply.text, status="single_shot", turns=1,
                         in_tokens=reply.in_tokens, out_tokens=reply.out_tokens)


if __name__ == "__main__":
    cli(BareModel)
