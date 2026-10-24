"""Chorus engine: posts -> signals -> convergence -> market check -> practice position.

Everything here is PAPER trading: positions live in memory and in the trail file.
There is no exchange connector and no order code anywhere in this project.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from .market import Prices
from .nlp import read_post
from .trail import Trail, sha

DEFAULT_CONFIG = {
    "voices": [],                     # [{"source","handle","weight"}], max 20
    "signal": {
        "window_h": 12,               # signals older than this do not count toward convergence
        "min_voices": 2,              # distinct voices on the same token + direction
        "min_score": 1.0,             # sum of trust * conviction * recency * (1 + urgency/2)
        "max_opposition": 0.5,        # opposing score must be below this share of the score
        "maturity_h": 24,             # when a call is graded to update the voice's trust
    },
    "market": {
        "momentum_h": 6,              # look-back for "does the market agree?"
        "max_adverse": 0.03,          # skip if price already moved >3% against the narrative
        "max_chase": 0.08,            # skip if price already moved >8% with it (priced in)
    },
    "risk": {                         # user-defined limits; every trade is checked against them
        "start_equity": 10_000.0,
        "max_position_pct": 0.10,
        "max_total_exposure_pct": 0.30,
        "max_open": 3,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
        "max_hold_h": 48,
        "cooldown_h": 12,
        "allow_short": True,
    },
}
MAX_VOICES = 20


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(iso: str) -> int:
    return int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def merge(base: dict, over: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Chorus:
    def __init__(self, config: dict, posts: list[dict], prices_snapshot: dict):
        self.cfg = merge(DEFAULT_CONFIG, config)
        voices = self.cfg["voices"]
        if len(voices) > MAX_VOICES:
            raise ValueError(f"at most {MAX_VOICES} voices (got {len(voices)})")
        self.weight = {v["handle"]: float(v.get("weight", 1.0)) for v in voices}
        self.posts = sorted((p for p in posts if p["voice"] in self.weight or not voices),
                            key=lambda p: (p["ts"], p["id"]))
        self.prices = Prices(prices_snapshot)
        self.trail = Trail({
            "agent": "chorus-kol-agent/1.0", "mode": "paper-trading-only",
            "config_hash": sha(self.cfg), "posts_hash": sha(self.posts),
            "prices_hash": sha(prices_snapshot), "n_posts": len(self.posts),
        })
        self.signals: list[dict] = []
        self.hits = defaultdict(lambda: [1.0, 1.0])   # voice -> Beta(a, b) of correct calls
        self.open: dict[str, dict] = {}
        self.closed: list[dict] = []
        self.cash = self.cfg["risk"]["start_equity"]
        self.last_trade_ms: dict[str, int] = {}
        self.equity_curve: list[tuple[int, float]] = []

    # ---------- trust -------------------------------------------------------------
    def trust(self, voice: str) -> float:
        a, b = self.hits[voice]
        return round(self.weight.get(voice, 1.0) * 2 * a / (a + b), 4)

    def _grade_mature(self, now_ms: int):
        mat = self.cfg["signal"]["maturity_h"] * 3600_000
        for s in self.signals:
            if s["graded"] or now_ms - s["t"] < mat:
                continue
            ch = self.prices.change(s["token"], s["t"] + mat, mat / 3600_000)
            s["graded"] = True
            if ch is None:
                continue
            correct = (ch > 0) == (s["direction"] > 0)
            before = self.trust(s["voice"])
            self.hits[s["voice"]][0 if correct else 1] += 1
            self.trail.add("trust_update", _iso(s["t"] + mat), voice=s["voice"],
                           token=s["token"], call=s["direction"], move_24h=round(ch, 4),
                           correct=correct, trust_before=before, trust_after=self.trust(s["voice"]),
                           post=s["url"])

    # ---------- ingestion -------------------------------------------------------------
    def _ingest(self, post: dict) -> list[str]:
        r = read_post(post["text"])
        touched = []
        t = _ms(post["ts"])
        for tok, call in r["calls"].items():
            if call["direction"] == 0 or not self.prices.has(tok):
                continue
            sig = {"t": t, "voice": post["voice"], "token": tok, "direction": call["direction"],
                   "conviction": r["conviction"], "urgency": r["urgency"], "url": post["url"],
                   "graded": False}
            self.signals.append(sig)
            touched.append(tok)
            self.trail.add("signal", post["ts"], voice=post["voice"], token=tok,
                           direction=call["direction"], sentiment=call["sentiment"],
                           conviction=r["conviction"], urgency=r["urgency"],
                           why={**call["why"], **r["why"]},
                           trust=self.trust(post["voice"]), post=post["url"],
                           quote=call["evidence"])
        return touched

    # ---------- convergence -----------------------------------------------------------
    def _side_score(self, token: str, direction: int, now_ms: int):
        win = self.cfg["signal"]["window_h"] * 3600_000
        best: dict[str, dict] = {}
        for s in self.signals:
            if s["token"] != token or s["direction"] != direction or not 0 <= now_ms - s["t"] <= win:
                continue
            recency = math.exp(-(now_ms - s["t"]) / win)
            part = self.trust(s["voice"]) * s["conviction"] * recency * (1 + s["urgency"] / 2)
            if s["voice"] not in best or part > best[s["voice"]]["part"]:
                best[s["voice"]] = {"part": round(part, 4), "url": s["url"]}
        return round(sum(v["part"] for v in best.values()), 4), best

    def _consider(self, token: str, now_ms: int):
        sc, mk, rk = self.cfg["signal"], self.cfg["market"], self.cfg["risk"]
        bull, bull_v = self._side_score(token, 1, now_ms)
        bear, bear_v = self._side_score(token, -1, now_ms)
        direction, score, voters, opp = (1, bull, bull_v, bear) if bull >= bear else (-1, bear, bear_v, bull)
        checks = {
            "distinct_voices": [len(voters), sc["min_voices"], len(voters) >= sc["min_voices"]],
            "score": [score, sc["min_score"], score >= sc["min_score"]],
            "opposition": [opp, round(sc["max_opposition"] * score, 4), opp < sc["max_opposition"] * score],
        }
        if len(voters) < sc["min_voices"]:
            return  # not a convergence candidate; the signals are already in the trail
        mom = self.prices.change(token, now_ms, mk["momentum_h"])
        aligned = None if mom is None else mom * direction
        checks["market_not_against"] = [aligned, -mk["max_adverse"], aligned is not None and aligned > -mk["max_adverse"]]
        checks["not_priced_in"] = [aligned, mk["max_chase"], aligned is not None and aligned < mk["max_chase"]]
        checks["short_allowed"] = [direction, "allow_short", direction > 0 or rk["allow_short"]]
        last = self.last_trade_ms.get(token)
        checks["cooldown"] = [None if last is None else round((now_ms - last) / 3600_000, 1),
                              rk["cooldown_h"], last is None or now_ms - last >= rk["cooldown_h"] * 3600_000]
        checks["no_open_position"] = [token in self.open, False, token not in self.open]
        checks["max_open"] = [len(self.open), rk["max_open"], len(self.open) < rk["max_open"]]
        equity = self.equity(now_ms)
        exposure = sum(p["notional"] for p in self.open.values())
        size_pct = min(rk["max_position_pct"], rk["max_position_pct"] * score / (2 * sc["min_score"]))
        notional = round(equity * size_pct, 2)
        cap = equity * rk["max_total_exposure_pct"] - exposure
        checks["exposure"] = [round(exposure + notional, 2), round(equity * rk["max_total_exposure_pct"], 2), notional <= cap]
        ok = all(c[2] for c in checks.values())
        px = self.prices.at(token, now_ms)
        rec = self.trail.add("convergence", _iso(now_ms), token=token, direction=direction,
                             score=score, opposition=opp, voices=voters, momentum=mom,
                             checks=checks, decision="OPEN" if ok else "SKIP",
                             failed=[k for k, c in checks.items() if not c[2]])
        if not ok or not px:
            return
        entry = px[1]
        pos = {"token": token, "direction": direction, "entry": entry, "t_open": now_ms,
               "notional": notional, "qty": notional / entry,
               "stop": entry * (1 - direction * rk["stop_loss_pct"]),
               "take": entry * (1 + direction * rk["take_profit_pct"]),
               "deadline": now_ms + rk["max_hold_h"] * 3600_000, "because": rec["hash"],
               "voices": sorted(voters)}
        self.open[token] = pos
        self.cash -= notional
        self.last_trade_ms[token] = now_ms
        self.trail.add("practice_open", _iso(now_ms), token=token,
                       side="LONG" if direction > 0 else "SHORT", entry=entry, notional=notional,
                       size_pct=round(size_pct, 4), stop=round(pos["stop"], 6),
                       take=round(pos["take"], 6), max_hold_h=rk["max_hold_h"],
                       because=rec["hash"], note="paper trade, no order sent anywhere")

    # ---------- positions ---------------------------------------------------------------
    def _mark(self, p: dict, price: float) -> float:
        return p["notional"] + p["direction"] * p["qty"] * (price - p["entry"])

    def equity(self, now_ms: int) -> float:
        val = self.cash
        for p in self.open.values():
            px = self.prices.at(p["token"], now_ms)
            val += self._mark(p, px[1] if px else p["entry"])
        return round(val, 2)

    def _check_exits(self, prev_ms: int, now_ms: int):
        for tok in list(self.open):
            p = self.open[tok]
            reason, exit_px, exit_ms = None, None, None
            for t, price, _ in self.prices.path(tok, prev_ms, now_ms):
                hit_stop = price <= p["stop"] if p["direction"] > 0 else price >= p["stop"]
                hit_take = price >= p["take"] if p["direction"] > 0 else price <= p["take"]
                if hit_stop or hit_take or t >= p["deadline"]:
                    reason = "stop_loss" if hit_stop else "take_profit" if hit_take else "time_stop"
                    exit_px, exit_ms = price, t
                    break
            if not reason:
                continue
            value = self._mark(p, exit_px)
            self.cash += value
            pnl = round(value - p["notional"], 2)
            ret = round(p["direction"] * (exit_px / p["entry"] - 1), 4)
            closed = {**p, "exit": exit_px, "t_close": exit_ms, "reason": reason, "pnl": pnl, "ret": ret}
            self.closed.append(closed)
            del self.open[tok]
            self.trail.add("practice_close", _iso(exit_ms), token=tok, reason=reason,
                           entry=p["entry"], exit=exit_px, ret=ret, pnl=pnl,
                           held_h=round((exit_ms - p["t_open"]) / 3600_000, 1), opened_by=p["because"])

    # ---------- main loop ----------------------------------------------------------------
    def run(self) -> dict:
        if not self.posts:
            return self.summary()
        start = _ms(self.posts[0]["ts"]) // 3600_000 * 3600_000
        end = self.prices.end_ms()
        i, prev = 0, start
        t = start
        while t <= end + 3600_000:
            touched = set()
            while i < len(self.posts) and _ms(self.posts[i]["ts"]) <= t:
                touched.update(self._ingest(self.posts[i]))
                i += 1
            self._grade_mature(t)
            self._check_exits(prev, t)
            for tok in sorted(touched):
                self._consider(tok, t)
            self.equity_curve.append((t, self.equity(t)))
            prev, t = t, t + 3600_000
        return self.summary()

    def summary(self) -> dict:
        wins = [c for c in self.closed if c["pnl"] > 0]
        end_eq = self.equity_curve[-1][1] if self.equity_curve else self.cfg["risk"]["start_equity"]
        return {
            "posts": len(self.posts), "signals": len(self.signals),
            "convergences": sum(r["kind"] == "convergence" for r in self.trail.records),
            "opened": sum(r["kind"] == "practice_open" for r in self.trail.records),
            "closed": len(self.closed), "still_open": len(self.open),
            "win_rate": round(len(wins) / len(self.closed), 3) if self.closed else None,
            "start_equity": self.cfg["risk"]["start_equity"], "end_equity": end_eq,
            "paper_return": round(end_eq / self.cfg["risk"]["start_equity"] - 1, 4),
            "trail_head": self.trail.head,
            "trust": {v: self.trust(v) for v in sorted(self.weight or {s["voice"] for s in self.signals})},
        }
