"""Loads config.toml and resolves the repository paths the agent works in."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    model: str
    effort: str
    max_tokens: int
    starting_balance_eur: float
    max_cycle_eur: float
    max_daily_eur: float
    min_call_reserve_eur: float
    max_steps: int
    usd_per_eur: float
    safety_margin: float
    default_sleep_hours: float
    min_sleep_hours: float
    max_sleep_hours: float
    web_search_max_uses: int
    web_fetch_max_uses: int
    max_file_bytes: int
    max_human_requests_per_cycle: int
    max_open_human_requests: int
    storefront: dict = field(default_factory=dict)
    root: Path = ROOT

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def site_dir(self) -> Path:
        return self.root / "site"

    @property
    def products_dir(self) -> Path:
        return self.root / "products"


def load_config(path: Path | None = None, root: Path = ROOT) -> Config:
    path = path or root / "config.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    m, b, t = raw["model"], raw["budget"], raw["tools"]
    return Config(
        model=m["name"],
        effort=m["effort"],
        max_tokens=int(m["max_tokens"]),
        starting_balance_eur=float(b["starting_balance_eur"]),
        max_cycle_eur=float(b["max_cycle_eur"]),
        max_daily_eur=float(b["max_daily_eur"]),
        min_call_reserve_eur=float(b["min_call_reserve_eur"]),
        max_steps=int(b["max_steps"]),
        usd_per_eur=float(b["usd_per_eur"]),
        safety_margin=float(b["safety_margin"]),
        default_sleep_hours=float(b["default_sleep_hours"]),
        min_sleep_hours=float(b["min_sleep_hours"]),
        max_sleep_hours=float(b["max_sleep_hours"]),
        web_search_max_uses=int(t["web_search_max_uses"]),
        web_fetch_max_uses=int(t["web_fetch_max_uses"]),
        max_file_bytes=int(t["max_file_bytes"]),
        max_human_requests_per_cycle=int(t["max_human_requests_per_cycle"]),
        max_open_human_requests=int(t["max_open_human_requests"]),
        storefront=dict(raw.get("storefront", {})),
        root=root,
    )
