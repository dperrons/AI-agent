"""Tools the agent can call, and the sandbox that executes them."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .external import GitHub


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


_PATH = {"type": "string", "description": "Path relative to the repository, under site/ or products/."}

CUSTOM_TOOLS = [
    _tool("get_status", "Current balance, spending this cycle, and storefront links.", {}, []),
    _tool("list_files", "List files under site/ or products/.",
          {"directory": {"type": "string", "enum": ["site", "products"]}}, ["directory"]),
    _tool("read_file", "Read a text file under site/ or products/.", {"path": _PATH}, ["path"]),
    _tool("write_file",
          "Create or overwrite a text file under site/ (published publicly) or products/.",
          {"path": _PATH, "content": {"type": "string"}}, ["path", "content"]),
    _tool("delete_file", "Delete a file under site/ or products/.", {"path": _PATH}, ["path"]),
    _tool("update_memory",
          "Replace your long-term memory (markdown). This is the only thing you remember next cycle "
          "besides the journal, so include strategy, experiments, results and pending items.",
          {"content": {"type": "string"}}, ["content"]),
    _tool("request_human",
          "Open a request to your creator for something only a human can do. Be concrete: steps, "
          "reason, expected payoff, and any cost needing approval.",
          {"title": {"type": "string"}, "body": {"type": "string"}}, ["title", "body"]),
    _tool("check_human_requests", "List your requests to your creator with their replies.", {}, []),
    _tool("schedule_next_wakeup",
          "Choose how many hours to sleep before your next cycle (3 to 168). Sleep is free.",
          {"hours": {"type": "number"}, "reason": {"type": "string"}}, ["hours", "reason"]),
    _tool("end_cycle", "Finish this cycle. Call it last.",
          {"summary": {"type": "string", "description": "What you did and learned this cycle."}},
          ["summary"]),
]


def is_legacy_model(model: str) -> bool:
    """Haiku 4.5 lacks effort, adaptive thinking and the dynamic-filtering web tools."""
    return model.startswith("claude-haiku")


def server_tools(cfg: Config) -> list[dict]:
    search, fetch = (("web_search_20250305", "web_fetch_20250910") if is_legacy_model(cfg.model)
                     else ("web_search_20260209", "web_fetch_20260209"))
    return [
        {"type": search, "name": "web_search", "max_uses": cfg.web_search_max_uses},
        {"type": fetch, "name": "web_fetch", "max_uses": cfg.web_fetch_max_uses},
    ]


class ToolError(Exception):
    pass


@dataclass
class Toolbox:
    cfg: Config
    ledger: "object"
    github: GitHub | None
    status_fn: "object"  # callable returning the status text
    requests_opened: int = 0
    ended: bool = False
    summary: str = ""
    sleep_hours: float | None = None
    sleep_reason: str = ""
    files_changed: list[str] = field(default_factory=list)

    # --- sandbox -----------------------------------------------------------
    def _resolve(self, rel: str) -> Path:
        path = (self.cfg.root / rel).resolve()
        for allowed in (self.cfg.site_dir, self.cfg.products_dir):
            if path == allowed or allowed.resolve() in path.parents:
                return path
        raise ToolError("Path must be inside site/ or products/.")

    # --- dispatch ----------------------------------------------------------
    def run(self, name: str, args: dict) -> str:
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            raise ToolError(f"Unknown tool {name}")
        return handler(**args)

    def t_get_status(self) -> str:
        return self.status_fn()

    def t_list_files(self, directory: str) -> str:
        base = self.cfg.root / directory
        files = sorted(str(p.relative_to(self.cfg.root)) for p in base.rglob("*") if p.is_file())
        return "\n".join(files) or "(empty)"

    def t_read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.is_file():
            raise ToolError("File not found.")
        return p.read_text(errors="replace")[: self.cfg.max_file_bytes]

    def t_write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        if len(content.encode()) > self.cfg.max_file_bytes:
            raise ToolError(f"File too large (max {self.cfg.max_file_bytes} bytes).")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self.files_changed.append(path)
        return f"Wrote {len(content)} chars to {path}."

    def t_delete_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.is_file():
            raise ToolError("File not found.")
        p.unlink()
        self.files_changed.append(path)
        return f"Deleted {path}."

    def t_update_memory(self, content: str) -> str:
        if len(content) > 20000:
            raise ToolError("Memory too long (max 20000 chars). Summarize.")
        (self.cfg.state_dir / "memory.md").write_text(content)
        return "Memory saved."

    def t_request_human(self, title: str, body: str) -> str:
        if self.requests_opened >= self.cfg.max_human_requests_per_cycle:
            raise ToolError("Request limit for this cycle reached.")
        log_path = self.cfg.state_dir / "human_requests.json"
        log = json.loads(log_path.read_text()) if log_path.exists() else []
        if sum(1 for r in log if r.get("open", True)) >= self.cfg.max_open_human_requests:
            raise ToolError("Too many open requests. Wait for your creator to answer.")
        entry = {"title": title, "body": body, "open": True}
        if self.github:
            entry.update(self.github.open_request(title, body + "\n\n---\n_Aperta da Survivor._"))
        log.append(entry)
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
        self.requests_opened += 1
        where = entry.get("url", "state/human_requests.json (no GitHub access)")
        return f"Request sent: {where}"

    def t_check_human_requests(self) -> str:
        return human_requests_text(self.cfg, self.github)

    def t_schedule_next_wakeup(self, hours: float, reason: str) -> str:
        self.sleep_hours = min(max(float(hours), 3.0), 168.0)
        self.sleep_reason = reason
        return f"Will sleep {self.sleep_hours:g} hours."

    def t_end_cycle(self, summary: str) -> str:
        self.ended = True
        self.summary = summary
        return "Cycle ended. Good night."


def human_requests_text(cfg: Config, github: GitHub | None) -> str:
    """Current state of the agent's requests, and syncs open/closed into the local log."""
    log_path = cfg.state_dir / "human_requests.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    if github:
        remote = github.list_requests()
        by_number = {r["number"]: r for r in remote}
        for entry in log:
            if entry.get("number") in by_number:
                entry["open"] = by_number[entry["number"]]["state"] == "open"
        log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
        if not remote:
            return "(no requests yet)"
        return json.dumps(remote, indent=1, ensure_ascii=False)
    if not log:
        return "(no requests yet)"
    return json.dumps([{"title": r["title"], "open": r.get("open", True)} for r in log], indent=1)
