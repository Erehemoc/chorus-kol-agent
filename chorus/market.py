"""Market evidence: hourly price and volume series from the free CoinGecko API.

A snapshot is plain JSON {symbol: [[unix_ms, price, volume_24h], ...]} so a run can be
replayed later on exactly the same numbers.
"""
from __future__ import annotations

import bisect
import json
import time
import urllib.request

from .nlp import UNIVERSE


def fetch_hourly(symbol: str, days: int = 30) -> list[list[float]]:
    cg_id = UNIVERSE[symbol][0]
    url = (f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
           f"?vs_currency=usd&days={days}")
    req = urllib.request.Request(url, headers={"User-Agent": "chorus-kol-agent"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    vols = dict((int(t), v) for t, v in data["total_volumes"])
    return [[int(t), p, vols.get(int(t), 0.0)] for t, p in data["prices"]]


def fetch_snapshot(symbols, days: int = 30, pause: float = 2.5) -> dict:
    snap = {}
    for s in sorted(set(symbols)):
        try:
            snap[s] = fetch_hourly(s, days)
        except Exception as e:  # missing coin, rate limit: recorded, never invented
            snap[s] = {"error": str(e)}
        time.sleep(pause)
    return snap


class Prices:
    def __init__(self, snapshot: dict):
        self.series = {s: v for s, v in snapshot.items() if isinstance(v, list) and v}
        self.ts = {s: [row[0] for row in v] for s, v in self.series.items()}

    def has(self, sym: str) -> bool:
        return sym in self.series

    def at(self, sym: str, t_ms: int):
        """Last known [t, price, vol] at or before t_ms (no look-ahead)."""
        if sym not in self.series:
            return None
        i = bisect.bisect_right(self.ts[sym], t_ms) - 1
        return self.series[sym][i] if i >= 0 else None

    def change(self, sym: str, t_ms: int, hours: float):
        now, then = self.at(sym, t_ms), self.at(sym, t_ms - int(hours * 3600_000))
        if not now or not then or then[1] == 0:
            return None
        return now[1] / then[1] - 1

    def path(self, sym: str, t0_ms: int, t1_ms: int):
        if sym not in self.series:
            return []
        lo = bisect.bisect_right(self.ts[sym], t0_ms)
        hi = bisect.bisect_right(self.ts[sym], t1_ms)
        return self.series[sym][lo:hi]

    def end_ms(self) -> int:
        return max((v[-1][0] for v in self.series.values()), default=0)
