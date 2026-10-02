"""The agent's bank account: every cent spent on thinking and every cent earned.

The ledger is the single source of truth for whether the agent is alive. Only
code outside the model can credit it (Stripe sync, owner-recorded income), so
the agent can never pay itself with an invented number.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# USD per million tokens: (input, output). Cache writes cost 1.25x input,
# cache reads 0.1x input.
PRICES_USD_PER_MTOK = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def usage_cost_usd(usage, model: str) -> float:
    """Cost of one Messages API response. Unknown models are priced as Fable (worst case)."""
    price_in, price_out = PRICES_USD_PER_MTOK.get(model, PRICES_USD_PER_MTOK["claude-fable-5-1"])
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    server = getattr(usage, "server_tool_use", None)
    searches = (getattr(server, "web_search_requests", 0) or 0) if server else 0
    return (
        tokens_in * price_in
        + cache_write * price_in * 1.25
        + cache_read * price_in * 0.10
        + tokens_out * price_out
    ) / 1_000_000 + searches * WEB_SEARCH_USD


class Ledger:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, path: Path, starting_balance_eur: float) -> "Ledger":
        if path.exists():
            return cls(path, json.loads(path.read_text()))
        born = iso(now())
        data = {
            "currency": "EUR",
            "born_at": born,
            "alive": True,
            "died_at": None,
            "balance_eur": round(starting_balance_eur, 6),
            "total_spent_eur": 0.0,
            "total_earned_eur": 0.0,
            "cycles": 0,
            "sleep_until": None,
            "stripe_synced_until": int(now().timestamp()),
            "transactions": [
                {"at": born, "type": "seed", "amount_eur": starting_balance_eur,
                 "note": "Capitale iniziale dal creatore"}
            ],
        }
        ledger = cls(path, data)
        ledger.save()
        return ledger

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the file reviewable: only the most recent transactions are stored in full.
        self.data["transactions"] = self.data["transactions"][-500:]
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    @property
    def balance(self) -> float:
        return self.data["balance_eur"]

    @property
    def alive(self) -> bool:
        return self.data["alive"]

    def _record(self, type_: str, amount_eur: float, note: str) -> None:
        self.data["balance_eur"] = round(self.data["balance_eur"] + amount_eur, 6)
        self.data["transactions"].append(
            {"at": iso(now()), "type": type_, "amount_eur": round(amount_eur, 6), "note": note}
        )

    def charge(self, amount_eur: float, note: str) -> None:
        self.data["total_spent_eur"] = round(self.data["total_spent_eur"] + amount_eur, 6)
        self._record("expense", -amount_eur, note)

    def credit(self, amount_eur: float, note: str) -> None:
        if amount_eur <= 0:
            raise ValueError("income must be positive")
        self.data["total_earned_eur"] = round(self.data["total_earned_eur"] + amount_eur, 6)
        self._record("income", amount_eur, note)
        if not self.alive and self.balance > 0:
            self.data["alive"] = True
            self.data["died_at"] = None
            self.data["transactions"].append(
                {"at": iso(now()), "type": "revival", "amount_eur": 0, "note": "Saldo tornato positivo"}
            )

    def die(self) -> None:
        self.data["alive"] = False
        self.data["died_at"] = iso(now())

    def set_sleep(self, hours: float) -> None:
        self.data["sleep_until"] = iso(now() + timedelta(hours=hours))

    def wake(self) -> None:
        self.data["sleep_until"] = None

    def asleep(self) -> bool:
        # A few minutes of slack: scheduled runs drift, and a 30-minute nap should not
        # turn into a 60-minute one because the alarm rang 2 minutes early.
        until = self.data.get("sleep_until")
        return bool(until) and datetime.fromisoformat(until) - timedelta(minutes=5) > now()

    def spent_last_24h(self) -> float:
        since = now() - timedelta(hours=24)
        return sum(-tx["amount_eur"] for tx in self.data["transactions"]
                   if tx["type"] == "expense" and datetime.fromisoformat(tx["at"]) > since)

    def recent(self, n: int = 15) -> list[dict]:
        return self.data["transactions"][-n:]
