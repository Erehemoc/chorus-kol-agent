"""Hash-chained reasoning trail.

Each record carries the hash of the previous one, so editing, dropping or reordering a
step breaks the chain. `verify()` checks the chain; `replay` (in cli.py) re-runs the agent
on the same frozen inputs and checks that it produces the identical chain.
"""
from __future__ import annotations

import hashlib
import json


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(obj) -> str:
    return hashlib.sha256(canon(obj).encode()).hexdigest()


class Trail:
    def __init__(self, genesis: dict):
        self.records: list[dict] = []
        self._prev = sha(genesis)
        self.genesis = genesis

    def add(self, kind: str, ts: str, **body) -> dict:
        rec = {"seq": len(self.records), "kind": kind, "ts": ts, **body, "prev": self._prev}
        rec["hash"] = sha({k: v for k, v in rec.items() if k != "hash"})
        self._prev = rec["hash"]
        self.records.append(rec)
        return rec

    @property
    def head(self) -> str:
        return self._prev

    def dump(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(canon({"kind": "genesis", **self.genesis}) + "\n")
            for r in self.records:
                f.write(canon(r) + "\n")


def verify(path: str) -> tuple[bool, str]:
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(x) for x in f if x.strip()]
    genesis = {k: v for k, v in lines[0].items() if k != "kind"}
    prev = sha(genesis)
    for r in lines[1:]:
        if r["prev"] != prev:
            return False, f"chain broken before seq {r['seq']}"
        h = sha({k: v for k, v in r.items() if k != "hash"})
        if h != r["hash"]:
            return False, f"record {r['seq']} was modified"
        prev = h
    return True, prev
