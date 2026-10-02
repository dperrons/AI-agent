"""Thin HTTP clients for the outside world: GitHub Issues (talking to the owner)
and Stripe (verifying real income). Standard library only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

REQUEST_LABEL = "survivor-request"


def _http(method: str, url: str, headers: dict, body: dict | None = None, form: bool = False):
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
        else:
            data = json.dumps(body).encode()
            headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


class GitHub:
    """Opens and reads issues on the agent's own repository.

    Only comments written by the repository owner are shown to the agent: anyone
    else commenting on a public issue is untrusted and could try to steer it.
    """

    def __init__(self, token: str, repo: str, owner: str):
        self.repo = repo
        self.owner = owner
        self.api = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @classmethod
    def from_env(cls) -> "GitHub | None":
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            return None
        owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
        return cls(token, repo, owner)

    def _ensure_label(self) -> None:
        try:
            _http("POST", f"{self.api}/labels", self.headers,
                  {"name": REQUEST_LABEL, "color": "d93f0b",
                   "description": "Richiesta dell'agente al creatore"})
        except urllib.error.HTTPError as e:
            if e.code != 422:  # 422 = already exists
                raise

    def open_request(self, title: str, body: str) -> dict:
        self._ensure_label()
        issue = _http("POST", f"{self.api}/issues", self.headers, {
            "title": f"[Survivor] {title}",
            "body": body,
            "labels": [REQUEST_LABEL],
            "assignees": [self.owner],
        })
        return {"number": issue["number"], "url": issue["html_url"]}

    def close_request(self, number: int, note: str) -> None:
        _http("POST", f"{self.api}/issues/{number}/comments", self.headers,
              {"body": f"Risolta da Survivor: {note}"})
        _http("PATCH", f"{self.api}/issues/{number}", self.headers, {"state": "closed"})

    def list_requests(self, limit: int = 10) -> list[dict]:
        issues = _http("GET", f"{self.api}/issues?labels={REQUEST_LABEL}&state=all"
                       f"&sort=updated&per_page={limit}", self.headers)
        out = []
        for issue in issues:
            comments = []
            if issue.get("comments"):
                for c in _http("GET", issue["comments_url"], self.headers):
                    if c["user"]["login"].lower() == self.owner.lower():
                        comments.append(c["body"][:2000])
            out.append({
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "owner_replies": comments[-5:],
            })
        return out


class Stripe:
    """Read-only view of payments received. Use a restricted key with read access
    to balance transactions only."""

    def __init__(self, key: str):
        self.headers = {"Authorization": f"Bearer {key}"}

    @classmethod
    def from_env(cls) -> "Stripe | None":
        key = os.environ.get("STRIPE_API_KEY")
        return cls(key) if key else None

    def income_since(self, ts: int) -> tuple[list[tuple[float, str, int]], int]:
        """Net EUR income from charges/payments created after `ts`.

        Returns ([(amount_eur, note, created)], newest_created)."""
        base = f"https://api.stripe.com/v1/balance_transactions?limit=100&created[gt]={ts}"
        txs, url = [], base
        while True:
            page = _http("GET", url, self.headers)
            txs.extend(page.get("data", []))
            if not page.get("has_more") or not txs:
                break
            url = f"{base}&starting_after={txs[-1]['id']}"
        items, newest = [], ts
        for tx in txs:
            newest = max(newest, tx["created"])
            if tx["type"] not in ("charge", "payment") or tx["currency"] != "eur":
                continue
            net = tx["net"] / 100  # net of Stripe fees
            if net > 0:
                items.append((net, f"Stripe {tx['id']}: {tx.get('description') or 'pagamento'}",
                              tx["created"]))
        return items, newest
