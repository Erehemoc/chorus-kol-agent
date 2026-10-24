"""chorus - Multi-KOL Narrative Agent (paper trading only).

  python -m chorus.cli collect --config config.json --days 14 --out data/
  python -m chorus.cli run     --config config.json --posts data/posts.jsonl \
                               --prices data/prices.json --trail out/trail.jsonl
  python -m chorus.cli verify  out/trail.jsonl
  python -m chorus.cli replay  --config config.json --posts data/posts.jsonl \
                               --prices data/prices.json --trail out/trail.jsonl
  python -m chorus.cli report  --config ... --posts ... --prices ... --out docs/index.html
  python -m chorus.cli watch   --config config.json --interval 900   # live, still paper only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import sources
from .engine import Chorus
from .market import fetch_snapshot
from .nlp import read_post
from .trail import verify


def _load(a):
    cfg = json.load(open(a.config))
    posts = sources.load_fixture(a.posts)
    prices = json.load(open(a.prices))
    return cfg, posts, prices


def cmd_collect(a):
    cfg = json.load(open(a.config))
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    posts = []
    for v in cfg["voices"]:
        try:
            got = sources.fetch_voice(v, since)
        except Exception as e:
            print(f"  {v['source']}:{v['handle']}: {e}", file=sys.stderr)
            continue
        print(f"  {v['source']}:{v['handle']}: {len(got)} posts")
        posts += got
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in sorted(posts, key=lambda p: (p["ts"], p["id"])):
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    toks = sorted({t for p in posts for t in read_post(p["text"])["tokens"]})
    snap = fetch_snapshot(toks, days=max(a.days + 3, 7))
    json.dump(snap, open(os.path.join(a.out, "prices.json"), "w"))
    print(f"{len(posts)} posts, prices for {len(toks)} tokens -> {a.out}")


def cmd_run(a):
    cfg, posts, prices = _load(a)
    agent = Chorus(cfg, posts, prices)
    summary = agent.run()
    os.makedirs(os.path.dirname(a.trail) or ".", exist_ok=True)
    agent.trail.dump(a.trail)
    print(json.dumps(summary, indent=2))
    return agent


def cmd_verify(a):
    ok, info = verify(a.trail)
    print(("OK  chain intact, head " if ok else "FAIL  ") + info)
    sys.exit(0 if ok else 1)


def cmd_replay(a):
    """Re-run on the same frozen inputs and compare with a stored trail, record by record."""
    cfg, posts, prices = _load(a)
    agent = Chorus(cfg, posts, prices)
    agent.run()
    stored = [json.loads(x) for x in open(a.trail) if x.strip()][1:]
    fresh = agent.trail.records
    for i, (x, y) in enumerate(zip(stored, fresh)):
        if x["hash"] != y["hash"]:
            print(f"DIVERGED at seq {i}: stored {x['kind']} vs replay {y['kind']}")
            sys.exit(1)
    if len(stored) != len(fresh):
        print(f"DIVERGED: stored {len(stored)} records, replay {len(fresh)}")
        sys.exit(1)
    print(f"REPLAY OK  {len(fresh)} records identical, head {agent.trail.head}")


def cmd_report(a):
    from .report import render
    cfg, posts, prices = _load(a)
    agent = Chorus(cfg, posts, prices)
    agent.run()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    if a.trail:
        os.makedirs(os.path.dirname(a.trail) or ".", exist_ok=True)
        agent.trail.dump(a.trail)
    open(a.out, "w", encoding="utf-8").write(render(agent))
    print("report ->", a.out)


def cmd_watch(a):
    """Live loop: refresh public posts + prices, re-run, rewrite trail and report.

    Each cycle is a full deterministic run on a new frozen snapshot, saved under
    out/snapshots/<time>/ so any past decision can be replayed later.
    """
    import time
    from .report import render
    while True:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap_dir = os.path.join("out", "snapshots", stamp)
        cmd_collect(argparse.Namespace(config=a.config, days=a.days, out=snap_dir))
        ns = argparse.Namespace(config=a.config, posts=os.path.join(snap_dir, "posts.jsonl"),
                                prices=os.path.join(snap_dir, "prices.json"))
        cfg, posts, prices = _load(ns)
        agent = Chorus(cfg, posts, prices)
        s = agent.run()
        agent.trail.dump(os.path.join(snap_dir, "trail.jsonl"))
        open(a.out, "w", encoding="utf-8").write(render(agent))
        new = [r for r in agent.trail.records if r["kind"] in ("practice_open", "practice_close")][-3:]
        print(stamp, "open:", s["still_open"], "paper return:", s["paper_return"], "latest:",
              [(r["kind"], r["token"], r["ts"]) for r in new])
        if a.once:
            break
        time.sleep(a.interval)


def main(argv=None):
    p = argparse.ArgumentParser(prog="chorus", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", default="config.json")
        sp.add_argument("--posts", default="data/posts.jsonl")
        sp.add_argument("--prices", default="data/prices.json")

    c = sub.add_parser("collect"); c.add_argument("--config", default="config.json")
    c.add_argument("--days", type=int, default=14); c.add_argument("--out", default="data")
    r = sub.add_parser("run"); common(r); r.add_argument("--trail", default="out/trail.jsonl")
    v = sub.add_parser("verify"); v.add_argument("trail")
    rp = sub.add_parser("replay"); common(rp); rp.add_argument("--trail", default="out/trail.jsonl")
    rep = sub.add_parser("report"); common(rep); rep.add_argument("--out", default="docs/index.html")
    rep.add_argument("--trail", default=None)
    w = sub.add_parser("watch"); w.add_argument("--config", default="config.json")
    w.add_argument("--days", type=int, default=3); w.add_argument("--interval", type=int, default=900)
    w.add_argument("--out", default="docs/live.html"); w.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    {"collect": cmd_collect, "run": cmd_run, "verify": cmd_verify,
     "replay": cmd_replay, "report": cmd_report, "watch": cmd_watch}[a.cmd](a)


if __name__ == "__main__":
    main()
