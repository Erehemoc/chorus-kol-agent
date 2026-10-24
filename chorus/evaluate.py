"""Cause-and-effect checks: what would each decision have done?

For every convergence the agent saw, we simulate the same practice position with the same
risk rules (stop, take-profit, time stop), whether the agent opened it or skipped it.
That shows what the gates contributed, without changing the agent's own trail.
"""
from __future__ import annotations

from .engine import _ms
from .market import Prices


def hypothetical(prices: Prices, rec: dict, risk: dict) -> float | None:
    tok, d, t0 = rec["token"], rec["direction"], _ms(rec["ts"])
    px = prices.at(tok, t0)
    if not px:
        return None
    entry = px[1]
    stop = entry * (1 - d * risk["stop_loss_pct"])
    take = entry * (1 + d * risk["take_profit_pct"])
    path = prices.path(tok, t0, t0 + risk["max_hold_h"] * 3600_000)
    if not path:
        return None
    for _, p, _ in path:
        if (p <= stop if d > 0 else p >= stop) or (p >= take if d > 0 else p <= take):
            return round(d * (p / entry - 1), 4)
    return round(d * (path[-1][1] / entry - 1), 4)


def gate_report(records: list[dict], prices: Prices, risk: dict) -> dict:
    groups: dict[str, list[float]] = {"OPEN": [], "SKIP": []}
    by_gate: dict[str, list[float]] = {}
    for r in records:
        if r["kind"] != "convergence":
            continue
        h = hypothetical(prices, r, risk)
        if h is None:
            continue
        groups[r["decision"]].append(h)
        for g in r["failed"]:
            by_gate.setdefault(g, []).append(h)

    def stats(xs):
        if not xs:
            return {"n": 0}
        return {"n": len(xs), "avg_ret": round(sum(xs) / len(xs), 4),
                "hit_rate": round(sum(x > 0 for x in xs) / len(xs), 3)}

    return {"opened": stats(groups["OPEN"]), "skipped": stats(groups["SKIP"]),
            "skipped_by_gate": {g: stats(v) for g, v in sorted(by_gate.items())}}
