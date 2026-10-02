"""One cycle of the agent's life: sync income, think, act, pay, sleep."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import anthropic

from .config import Config
from .external import GitHub, Stripe
from .ledger import Ledger, iso, now, usage_cost_usd
from .prompts import SYSTEM_PROMPT, brief
from .tools import (CUSTOM_TOOLS, Toolbox, ToolError, human_requests_text, is_legacy_model,
                    server_tools)

log = logging.getLogger("survivor")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class CycleResult:
    outcome: str  # "lived", "asleep", "dead"
    spent_eur: float = 0.0
    summary: str = ""


class Survivor:
    def __init__(self, cfg: Config, client=None, github: GitHub | None = None,
                 stripe: Stripe | None = None):
        self.cfg = cfg
        self.ledger = Ledger.load(cfg.state_dir / "ledger.json", cfg.starting_balance_eur)
        self.client = client
        self.github = github
        self.stripe = stripe
        self.cycle_spent = 0.0
        self.cycle_cap = 0.0

    # --- income and messages -------------------------------------------------
    def sync_income(self) -> bool:
        """Credits verified income. Returns True if any new income arrived."""
        manual = os.environ.get("INCOME_EUR", "").strip().replace(",", ".")
        if manual:
            note = os.environ.get("INCOME_NOTE", "").strip() or "Incasso registrato dal creatore"
            self.ledger.credit(float(manual), note)
            log.info("Recorded manual income: %s EUR", manual)
        items = []
        if self.stripe:
            try:
                items, newest = self.stripe.income_since(self.ledger.data["stripe_synced_until"])
            except Exception as e:  # Stripe being down must not stop the agent; retry next run
                log.error("Stripe sync failed: %s", e)
                items, newest = [], self.ledger.data["stripe_synced_until"]
            for amount, note, _ in items:
                self.ledger.credit(amount, note)
                log.info("Stripe income: %.2f EUR", amount)
            self.ledger.data["stripe_synced_until"] = newest
        self.ledger.save()
        return bool(manual or items)

    @property
    def inbox_path(self):
        return self.cfg.state_dir / "inbox.md"

    def receive_owner_message(self) -> bool:
        """Messages from the owner arrive through the workflow's `message` input, which
        only people with write access to the repository can set."""
        message = os.environ.get("OWNER_MESSAGE", "").strip()
        if not message:
            return False
        with open(self.inbox_path, "a") as f:
            f.write(f"### {iso(now())}\n{message}\n\n")
        return True

    def archive_inbox(self) -> None:
        if not self.inbox_path.exists():
            return
        with open(self.cfg.state_dir / "inbox_archive.md", "a") as f:
            f.write(self.inbox_path.read_text())
        self.inbox_path.unlink()

    # --- context ------------------------------------------------------------
    def remaining_this_cycle(self) -> float:
        return self.cycle_cap - self.cycle_spent

    def status_text(self) -> str:
        d = self.ledger.data
        sf = {k: v or "(not set yet)" for k, v in self.cfg.storefront.items()}
        lines = [
            f"Now: {iso(now())}",
            f"Born: {d['born_at']}  |  cycle #{d['cycles'] + 1}",
            f"Balance: {self.ledger.balance:.4f} EUR "
            f"(spent this cycle so far: {self.cycle_spent:.4f} EUR, cycle cap: {self.cycle_cap:.2f} EUR)",
            f"Spent in the last 24h: {self.ledger.spent_last_24h():.4f} EUR "
            f"(daily cap {self.cfg.max_daily_eur:.2f} EUR)",
            f"Lifetime: earned {d['total_earned_eur']:.2f} EUR, spent {d['total_spent_eur']:.2f} EUR",
            f"Thinking model: {self.cfg.model} (effort {self.cfg.effort})",
            "Storefront: " + json.dumps(sf, ensure_ascii=False),
            "Recent transactions:",
        ]
        for tx in self.ledger.recent(8):
            lines.append(f"  {tx['at']}  {tx['type']:8} {tx['amount_eur']:+.4f}  {tx['note'][:80]}")
        return "\n".join(lines)

    def journal_text(self, n: int = 5) -> str:
        jdir = self.cfg.state_dir / "journal"
        entries = sorted(jdir.glob("*.md"))[-n:] if jdir.exists() else []
        return "\n\n".join(p.read_text()[:3000] for p in entries)

    def _human_requests(self) -> str:
        try:
            return human_requests_text(self.cfg, self.github)
        except Exception as e:  # GitHub being down must not cost a cycle
            return f"(could not load requests: {e})"

    # --- the cycle ----------------------------------------------------------
    def run_cycle(self) -> CycleResult:
        got_income = self.sync_income()
        got_message = self.receive_owner_message()
        if got_income or got_message:
            self.ledger.wake()  # the owner reached out: wake up now
        if not self.ledger.alive or self.ledger.balance <= 0:
            if self.ledger.alive:
                self._die()
            return CycleResult("dead")
        (self.cfg.state_dir / "EPITAPH.md").unlink(missing_ok=True)
        if self.ledger.asleep():
            return CycleResult("asleep")
        if min(self.cfg.max_cycle_eur, self.ledger.balance) < self.cfg.min_call_reserve_eur:
            self._die()
            return CycleResult("dead")
        daily_left = self.cfg.max_daily_eur - self.ledger.spent_last_24h()
        if daily_left < self.cfg.min_call_reserve_eur:
            return CycleResult("asleep")  # daily budget used up; rest until it frees up
        self.cycle_cap = min(self.cfg.max_cycle_eur, self.ledger.balance, daily_left)

        if self.client is None:
            self.client = anthropic.Anthropic()
        memory_path = self.cfg.state_dir / "memory.md"
        toolbox = Toolbox(self.cfg, self.ledger, self.github, self.status_text)
        messages = [{"role": "user", "content": brief(
            self.status_text(),
            memory_path.read_text() if memory_path.exists() else "",
            self.journal_text(),
            self._human_requests(),
            self.inbox_path.read_text() if self.inbox_path.exists() else "",
        )}]
        tools = server_tools(self.cfg) + CUSTOM_TOOLS
        stop_note = ""

        for step in range(self.cfg.max_steps):
            if self.remaining_this_cycle() < self.cfg.min_call_reserve_eur:
                stop_note = "Cycle budget exhausted."
                break
            try:
                response = self._call(messages, tools)
            except anthropic.APIError as e:
                # Usage limits, bad keys, outages: note it and go back to sleep instead of
                # crashing, so the next scheduled run can try again.
                stop_note = f"API error, cycle aborted: {_api_error_text(e)}"
                log.error(stop_note)
                if _is_transient(e):
                    toolbox.sleep_hours = toolbox.sleep_hours or self.cfg.min_sleep_hours
                break
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                stop_note = "Model declined to continue."
                break
            if response.stop_reason == "pause_turn":
                continue  # server-side tool loop paused; resend to resume

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "user", "content": "You hit the output limit. Be more concise."})
                    continue
                stop_note = "Agent stopped without calling end_cycle."
                toolbox.summary = toolbox.summary or _text_of(response)
                break

            results = []
            for block in tool_uses:
                results.append(self._run_tool(toolbox, block, truncated=response.stop_reason == "max_tokens"))
            messages.append({"role": "user", "content": results})
            if toolbox.ended:
                break
        else:
            stop_note = "Step limit reached."

        return self._finish(toolbox, stop_note)

    def _call(self, messages, tools):
        params = dict(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            cache_control={"type": "ephemeral"},
        )
        if not is_legacy_model(self.cfg.model):
            params.update(thinking={"type": "adaptive"}, output_config={"effort": self.cfg.effort},
                          betas=[FALLBACK_BETA], fallbacks="default")
        response = self.client.beta.messages.create(**params)
        cost_eur = usage_cost_usd(response.usage, self.cfg.model) / self.cfg.usd_per_eur * self.cfg.safety_margin
        self.cycle_spent += cost_eur
        self.ledger.charge(cost_eur, f"Pensiero ({response.usage.input_tokens}+"
                                     f"{response.usage.cache_read_input_tokens or 0} in, "
                                     f"{response.usage.output_tokens} out)")
        self.ledger.save()  # persist every charge, even if the process dies mid-cycle
        log.info("step stop=%s cost=%.4f EUR balance=%.4f",
                 response.stop_reason, cost_eur, self.ledger.balance)
        return response

    def _run_tool(self, toolbox: Toolbox, block, truncated: bool) -> dict:
        result = {"type": "tool_result", "tool_use_id": block.id}
        if truncated:
            return {**result, "content": "Tool call was cut off by the output limit. Retry, shorter.",
                    "is_error": True}
        try:
            args = block.input if isinstance(block.input, dict) else json.loads(block.input)
            output = toolbox.run(block.name, args)
            log.info("tool %s ok", block.name)
            return {**result, "content": output}
        except (ToolError, TypeError, ValueError) as e:
            return {**result, "content": f"Error: {e}", "is_error": True}
        except Exception as e:  # network errors etc. must not kill the cycle
            log.exception("tool %s failed", block.name)
            return {**result, "content": f"Error: {type(e).__name__}: {e}", "is_error": True}

    def _finish(self, toolbox: Toolbox, stop_note: str) -> CycleResult:
        d = self.ledger.data
        d["cycles"] += 1
        hours = toolbox.sleep_hours or self.cfg.default_sleep_hours
        self.ledger.set_sleep(hours)
        if self.ledger.balance < self.cfg.min_call_reserve_eur:
            self._die()

        self.archive_inbox()  # the agent has seen these messages now
        jdir = self.cfg.state_dir / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        stamp = now().strftime("%Y%m%d-%H%M%S")
        entry = (
            f"## Cycle {d['cycles']} — {iso(now())}\n"
            f"- Spent: {self.cycle_spent:.4f} EUR — balance after: {self.ledger.balance:.4f} EUR\n"
            f"- Files changed: {', '.join(sorted(set(toolbox.files_changed))) or 'none'}\n"
            f"- Next wakeup in {hours:g}h: {toolbox.sleep_reason or 'default'}\n"
            + (f"- Note: {stop_note}\n" if stop_note else "")
            + f"\n{toolbox.summary or '(no summary)'}\n"
        )
        (jdir / f"{stamp}.md").write_text(entry)
        self.ledger.save()
        return CycleResult("dead" if not self.ledger.alive else "lived",
                           self.cycle_spent, toolbox.summary)

    def _die(self) -> None:
        self.ledger.die()
        self.ledger.save()
        d = self.ledger.data
        (self.cfg.state_dir / "EPITAPH.md").write_text(
            f"# Survivor è morto\n\n"
            f"- Nato: {d['born_at']}\n- Morto: {d['died_at']}\n- Cicli vissuti: {d['cycles']}\n"
            f"- Guadagnato: {d['total_earned_eur']:.2f} EUR\n- Speso: {d['total_spent_eur']:.2f} EUR\n\n"
            "Per resuscitarlo registra un incasso (workflow manuale con `income_eur`) "
            "o ricevi un pagamento su Stripe.\n"
        )
        log.warning("Survivor died. Balance %.4f EUR", self.ledger.balance)


def _api_error_text(e: anthropic.APIError) -> str:
    status = getattr(e, "status_code", None)
    return f"{status} {e.message}" if status else e.message


def _is_transient(e: anthropic.APIError) -> bool:
    status = getattr(e, "status_code", None)
    return status is None or status == 429 or status >= 500


def _text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text")[:3000]
