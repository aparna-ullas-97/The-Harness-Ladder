"""
common/tools.py  --  the tools the agent can use, all scoped to one workspace folder.

CONCEPT (stage 01): tools are a *contract* between deterministic code and a
non-deterministic model. Three design rules are baked in here:
  1. few, clear tools with descriptions written like onboarding notes
  2. outputs are size-capped (a huge file must not eat the context window)
  3. errors say HOW to fix the call, not just that it failed

SAFETY FLOOR: run_shell / run_python really execute on your machine. A tiny floor below
refuses `..`, `~`, absolute paths and sudo so a live model cannot leave the workspace.
That floor is NOT the permission system from stage 06 (that one is project policy).
For live runs, prefer a throwaway container anyway.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_READ = 5000      # chars returned by one read_file call
MAX_OUT = 3000       # chars returned by shell / python


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ---------- helpers ----------
    def _p(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root != p and self.root not in p.parents:
            raise ValueError(f"path '{rel}' is outside the workspace. Use a relative path such as 'src/app.py'.")
        return p

    # ---------- tools (each returns plain text; raise ValueError for a fixable mistake) ----------
    def list_files(self, path: str = ".") -> str:
        p = self._p(path)
        if not p.exists():
            raise ValueError(f"'{path}' does not exist. Call list_files with path='.' to see the top level.")
        if p.is_file():
            return f"{path} is a file ({p.stat().st_size} bytes). Use read_file to open it."
        rows = []
        for c in sorted(p.iterdir()):
            if c.name.startswith(".harness") or c.name == "__pycache__":
                continue
            rows.append(f"{c.name}/" if c.is_dir() else f"{c.name} ({c.stat().st_size} bytes)")
        return "\n".join(rows) or "(empty folder)"

    def read_file(self, path: str, offset: int = 0) -> str:
        p = self._p(path)
        if not p.is_file():
            raise ValueError(f"'{path}' is not a file. Use list_files to find the exact name.")
        text = p.read_text(errors="replace")
        chunk = text[offset: offset + MAX_READ]
        end = offset + len(chunk)
        if end < len(text):
            chunk += f"\n[truncated: showed chars {offset}-{end} of {len(text)}. Call read_file again with offset={end} for more]"
        return chunk

    def write_file(self, path: str, content: str) -> str:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {path}"

    def edit_file(self, path: str, old: str, new: str) -> str:
        p = self._p(path)
        if not p.is_file():
            raise ValueError(f"'{path}' is not a file. Use list_files to find the exact name.")
        text = p.read_text()
        n = text.count(old)
        if n != 1:
            raise ValueError(f"'old' must match exactly once, but it matched {n} times. "
                             f"Copy the exact text from read_file, with enough surrounding lines to be unique.")
        p.write_text(text.replace(old, new))
        return f"edited {path}"

    def run_python(self, code: str) -> str:
        return self._run([sys.executable, "-c", code], shell=False)

    def run_shell(self, command: str) -> str:
        bad = _floor_violation(command)
        if bad:
            raise ValueError(f"command refused by the sandbox floor ({bad}). Stay inside the workspace with relative paths.")
        return self._run(command, shell=True)

    def check(self, command: str) -> tuple[bool, str]:
        """Run a command for the HARNESS (not the model). Returns (passed, output). Used by stage 07."""
        r = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    def _run(self, cmd, shell: bool) -> str:
        try:
            r = subprocess.run(cmd, shell=shell, cwd=self.root, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            raise ValueError("command timed out after 20s. Make it cheaper or split it up.")
        out = (r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")).strip()
        if len(out) > MAX_OUT:
            out = out[:MAX_OUT] + f"\n[output cut at {MAX_OUT} chars]"
        if r.returncode != 0:
            out += f"\n[exit code {r.returncode}]"
        return out or "(no output)"

    # ---------- registry ----------
    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if name not in SCHEMAS or fn is None:
            raise ValueError(f"unknown tool '{name}'. Available: {', '.join(SCHEMAS)}")
        try:
            return fn(**args)
        except TypeError as e:
            raise ValueError(f"bad arguments for {name}: {e}. Required: {SCHEMAS[name]['input_schema'].get('required', [])}")


def _floor_violation(cmd: str) -> str | None:
    if ".." in cmd or "~" in cmd or "$HOME" in cmd:
        return "parent/home path"
    if re.search(r"(^|[\s=;&|(])/[A-Za-z]", cmd):
        return "absolute path"
    if re.search(r"\bsudo\b", cmd):
        return "sudo"
    return None


def _schema(name, description, props, required):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props, "required": required}}


S = {"type": "string"}
SCHEMAS: dict[str, dict] = {s["name"]: s for s in [
    _schema("list_files", "List the files and folders directly inside a workspace folder. Start here when you do not know the layout.",
            {"path": {**S, "description": "relative folder, default '.'"}}, []),
    _schema("read_file", "Read a text file. Long files are returned in chunks of 5000 characters; the footer tells you the next offset.",
            {"path": S, "offset": {"type": "integer", "description": "character offset to start from, default 0"}}, ["path"]),
    _schema("write_file", "Create or overwrite a file with the full content given.",
            {"path": S, "content": S}, ["path", "content"]),
    _schema("edit_file", "Replace one exact piece of text in a file. 'old' must appear exactly once.",
            {"path": S, "old": S, "new": S}, ["path", "old", "new"]),
    _schema("run_python", "Run a short Python snippet inside the workspace and return stdout. Prefer this for counting, summing and parsing.",
            {"code": S}, ["code"]),
    _schema("run_shell", "Run a shell command inside the workspace (tests, ls, rm of temp files). Output is capped at 3000 chars.",
            {"command": S}, ["command"]),
]}

BASE_TOOLS = list(SCHEMAS)          # names, in a stable order
READ_ONLY_TOOLS = ["list_files", "read_file"]


def schemas(names: list[str]) -> list[dict]:
    return [SCHEMAS[n] for n in names]
