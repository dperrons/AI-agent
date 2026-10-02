"""Offline tests: a fake Claude client drives full cycles without spending money."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from survivor.agent import Survivor
from survivor.config import load_config
from survivor.ledger import Ledger, usage_cost_usd
from survivor.tools import ToolError, Toolbox

REPO = Path(__file__).resolve().parent.parent


def usage(inp=10_000, out=2_000, searches=0):
    return NS(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0,
              cache_read_input_tokens=0, server_tool_use=NS(web_search_requests=searches))


def tool_use(id_, name, **args):
    return NS(type="tool_use", id=id_, name=name, input=args)


def response(blocks, stop="tool_use", u=None):
    return NS(content=blocks, stop_reason=stop, usage=u or usage())


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.toml", tmp_path / "config.toml")
    for d in ("state", "site", "products"):
        (tmp_path / d).mkdir()
    monkeypatch.delenv("INCOME_EUR", raising=False)
    return tmp_path


def test_usage_cost():
    cost = usage_cost_usd(usage(1_000_000, 100_000, searches=3), "claude-opus-5-5")
    assert cost == pytest.approx(4.0 + 2.0 + 0.03)


def test_full_cycle_charges_and_acts(root):
    cfg = load_config(root=root)
    client = FakeClient([
        response([tool_use("a", "write_file", path="site/index.html", content="<h1>hi</h1>"),
                  tool_use("b", "update_memory", content="plan: sell guides")]),
        response([tool_use("c", "schedule_next_wakeup", hours=24, reason="wait for traffic"),
                  tool_use("d", "end_cycle", summary="built the site")]),
    ])
    s = Survivor(cfg, client=client)
    result = s.run_cycle()

    assert result.outcome == "lived"
    assert (root / "site/index.html").read_text() == "<h1>hi</h1>"
    assert (root / "state/memory.md").read_text() == "plan: sell guides"
    ledger = json.loads((root / "state/ledger.json").read_text())
    assert ledger["cycles"] == 1
    assert ledger["balance_eur"] < 5.0
    assert ledger["balance_eur"] == pytest.approx(5.0 - result.spent_eur)
    assert len(list((root / "state/journal").glob("*.md"))) == 1
    # Tool results were returned in a single user message after each assistant turn.
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert client.calls[0]["fallbacks"] == "default"

    # Sleeping: the next run costs nothing.
    s2 = Survivor(cfg, client=FakeClient([]))
    assert s2.run_cycle().outcome == "asleep"


def test_cycle_cap_stops_spending(root):
    cfg = load_config(root=root)
    expensive = usage(inp=40_000, out=4_000)  # ~0.25 EUR per call > 0.20 cap
    client = FakeClient([response([tool_use(str(i), "get_status")], u=expensive) for i in range(5)])
    result = Survivor(cfg, client=client).run_cycle()
    assert len(client.calls) == 1
    assert result.outcome == "lived"


def test_dies_when_broke_and_revives_on_income(root, monkeypatch):
    cfg = load_config(root=root)
    ledger = Ledger.load(root / "state/ledger.json", 5.0)
    ledger.charge(4.99, "test")
    ledger.save()
    assert Survivor(cfg, client=FakeClient([])).run_cycle().outcome == "dead"
    assert (root / "state/EPITAPH.md").exists()

    monkeypatch.setenv("INCOME_EUR", "3,50")
    client = FakeClient([response([tool_use("a", "end_cycle", summary="back")])])
    assert Survivor(cfg, client=client).run_cycle().outcome == "lived"
    assert not (root / "state/EPITAPH.md").exists()


def test_sandbox_blocks_escape(root):
    cfg = load_config(root=root)
    tb = Toolbox(cfg, None, None, lambda: "")
    for bad in ("../x", "state/ledger.json", "site/../state/ledger.json", "/etc/passwd"):
        with pytest.raises(ToolError):
            tb.run("write_file", {"path": bad, "content": "x"})


def test_haiku_request_shape(root):
    (root / "config.toml").write_text(
        (root / "config.toml").read_text().replace('"claude-opus-5-5"', '"claude-haiku-4-5"'))
    client = FakeClient([response([tool_use("a", "end_cycle", summary="ok")])])
    Survivor(load_config(root=root), client=client).run_cycle()
    call = client.calls[0]
    assert "output_config" not in call and "fallbacks" not in call
    assert call["tools"][0]["type"] == "web_search_20250305"
