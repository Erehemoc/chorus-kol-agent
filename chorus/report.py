"""Static HTML report: every practice trade expands into the chain of evidence behind it."""
from __future__ import annotations

import html
import json

from .evaluate import gate_report, hypothetical
from .trail import sha

E = html.escape

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#17202a;--mute:#5b6570;--line:#e3e5e8;--acc:#2f5bea;
--good:#127a4a;--bad:#b3261e;--chip:#eef1f6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1217;--card:#171b22;
--ink:#e8ebef;--mute:#9aa4af;--line:#2a313b;--acc:#7c9cff;--good:#4cc38a;--bad:#ff6b61;--chip:#222833}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 10px}
.sub{color:var(--mute)}.badge{display:inline-block;background:#fde9c8;color:#7a4b00;
border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;letter-spacing:.02em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--mute);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:10px 0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;font-size:12.5px}
.num{text-align:right;font-variant-numeric:tabular-nums}.good{color:var(--good)}.bad{color:var(--bad)}
details{border:1px solid var(--line);border-radius:10px;background:var(--card);margin:8px 0}
summary{cursor:pointer;padding:11px 14px;list-style:none;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
summary::-webkit-details-marker{display:none}details[open] summary{border-bottom:1px solid var(--line)}
.body{padding:12px 14px}.chip{background:var(--chip);border-radius:6px;padding:1px 7px;font-size:12.5px}
.q{border-left:3px solid var(--acc);padding:4px 10px;margin:6px 0;color:var(--ink);font-size:13.5px}
.q a{color:var(--acc)}code,.mono{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
.flow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.flow div{background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:13.5px}.flow i{color:var(--mute)}
pre{background:var(--chip);padding:12px;border-radius:8px;overflow:auto}
.scroll{overflow-x:auto}
"""


def _pct(x, digits=2):
    return "—" if x is None else f"{x*100:+.{digits}f}%"


def _usd(x):
    return f"${x:,.2f}" if x >= 1 else f"${x:.6g}"


def _cls(x):
    return "" if x is None else ("good" if x > 0 else "bad" if x < 0 else "")


def _equity_svg(curve, w=1040, h=180):
    if len(curve) < 2:
        return ""
    xs = [t for t, _ in curve]
    ys = [v for _, v in curve]
    lo, hi = min(ys), max(ys)
    hi = hi if hi > lo else lo + 1
    pts = " ".join(f"{(t-xs[0])/(xs[-1]-xs[0])*w:.1f},{h-(v-lo)/(hi-lo)*(h-20)-10:.1f}"
                   for t, v in curve)
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="paper equity">'
            f'<polyline fill="none" stroke="var(--acc)" stroke-width="2" points="{pts}"/>'
            f'<text x="4" y="14" font-size="12" fill="var(--mute)">${hi:,.0f}</text>'
            f'<text x="4" y="{h-2}" font-size="12" fill="var(--mute)">${lo:,.0f}</text></svg>')


def render(agent) -> str:
    recs = agent.trail.records
    by_hash = {r["hash"]: r for r in recs}
    sig_by_url = {}
    for r in recs:
        if r["kind"] == "signal":
            sig_by_url.setdefault(r["post"], []).append(r)
    s = agent.summary()
    risk = agent.cfg["risk"]
    gates = gate_report(recs, agent.prices, risk)
    posts = agent.posts
    period = f"{posts[0]['ts'][:10]} → {posts[-1]['ts'][:10]}" if posts else "—"

    out = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>Chorus KOL Agent</title><style>{CSS}</style></head><body><div class=wrap>"]
    out.append("<span class=badge>PAPER TRADING ONLY · no orders, no exchange connection</span>")
    out.append("<h1>Chorus: Multi-KOL Narrative Agent</h1>")
    out.append(f"<div class=sub>Watches up to 20 chosen market voices, finds when trusted voices "
               f"converge on the same token and direction, checks the market, and records the "
               f"practice trade it would make, with every step hash-chained. Period {E(period)}.</div>")
    k = [("Voices", len(agent.weight)), ("Posts read", s["posts"]), ("Token calls", s["signals"]),
         ("Convergences", s["convergences"]), ("Practice trades", s["opened"]),
         ("Paper P&L", _pct(s["paper_return"])), ("Win rate", "—" if s["win_rate"] is None else f"{s['win_rate']*100:.0f}%")]
    out.append("<div class=grid>" + "".join(f"<div class=kpi><b>{E(str(v))}</b><span>{E(a)}</span></div>"
                                           for a, v in k) + "</div>")
    out.append(f"<div class=card><b>Reasoning trail</b> · {len(recs)} records, SHA-256 chained · head "
               f"<code>{agent.trail.head[:16]}…</code> · inputs: posts <code>{agent.trail.genesis['posts_hash'][:12]}</code>, "
               f"prices <code>{agent.trail.genesis['prices_hash'][:12]}</code>, config "
               f"<code>{agent.trail.genesis['config_hash'][:12]}</code>. Re-running on these inputs reproduces the "
               f"identical chain (<code>chorus replay</code>).</div>")

    out.append("<h2>How a decision is made</h2><div class=flow>"
               "<div>Post from a chosen voice</div><i>→</i><div>Token + direction per clause, conviction, urgency</div><i>→</i>"
               "<div>Weight by the voice's trust (graded on past calls)</div><i>→</i>"
               f"<div>Convergence: ≥{agent.cfg['signal']['min_voices']} voices, same token &amp; side, within {agent.cfg['signal']['window_h']} h</div><i>→</i>"
               "<div>Market check: not against, not priced in</div><i>→</i><div>Risk limits</div><i>→</i>"
               "<div>Practice position + exits</div></div>")

    # trades
    out.append("<h2>Practice trades and why</h2>")
    opens = [r for r in recs if r["kind"] == "practice_open"]
    closes = {r["opened_by"]: r for r in recs if r["kind"] == "practice_close"}
    for o in opens:
        conv = by_hash[o["because"]]
        c = closes.get(o["because"])
        ret = c["ret"] if c else None
        head = (f"<span class=chip>{E(o['ts'][:16].replace('T',' '))}</span><b>{E(o['side'])} {E(o['token'])}</b>"
                f"<span>entry {_usd(o['entry'])}</span><span>size {o['size_pct']*100:.1f}% of equity</span>"
                f"<span>{len(conv['voices'])} voices · score {conv['score']}</span>"
                + (f"<span class={_cls(ret)}>{_pct(ret)} · {E(c['reason'].replace('_',' '))} after {c['held_h']} h</span>"
                   if c else "<span class=chip>still open</span>"))
        body = ["<div class=body><b>Voices that converged</b>"]
        for voice, v in sorted(conv["voices"].items(), key=lambda kv: -kv[1]["part"]):
            sig = next((x for x in sig_by_url.get(v["url"], []) if x["token"] == conv["token"]), None)
            why = ""
            if sig:
                words = sig["why"].get("bull" if conv["direction"] > 0 else "bear", [])
                why = (f" · conviction {sig['conviction']} · urgency {sig['urgency']} · trust {sig['trust']}"
                       f" · words: {E(', '.join(words[:6]))}")
            quote = E(sig["quote"]) if sig else ""
            body.append(f"<div class=q><b>{E(voice)}</b> <span class=sub>weight in score {v['part']}{why}</span><br>"
                        f"{quote} <a href='{E(v['url'])}' target=_blank rel=noopener>source</a></div>")
        body.append("<b>Checks</b><div class=scroll><table><tr><th>Rule</th><th class=num>Value</th>"
                    "<th class=num>Limit</th><th>Result</th></tr>")
        for name, (val, lim, ok) in conv["checks"].items():
            fv = _pct(val) if name in ("market_not_against", "not_priced_in") and isinstance(val, (int, float)) else val
            fl = _pct(lim) if name in ("market_not_against", "not_priced_in") else lim
            body.append(f"<tr><td>{E(name.replace('_',' '))}</td><td class=num>{E(str(fv))}</td>"
                        f"<td class=num>{E(str(fl))}</td><td class={'good' if ok else 'bad'}>{'pass' if ok else 'fail'}</td></tr>")
        body.append("</table></div>")
        body.append(f"<p class=sub>Exits set at open: stop {_usd(o['stop'])}, take-profit {_usd(o['take'])}, "
                    f"time stop {o['max_hold_h']} h. Opposing score {conv['opposition']}, 6 h momentum "
                    f"{_pct(conv['momentum'])}. Trail records <code>{conv['hash'][:12]}</code> → "
                    f"<code>{o['hash'][:12]}</code>{' → <code>'+c['hash'][:12]+'</code>' if c else ''}.</p></div>")
        out.append(f"<details><summary>{head}</summary>{''.join(body)}</details>")

    # gates
    out.append("<h2>What the rules filtered out</h2><div class=card><p class=sub>Every convergence the agent "
               "saw, replayed with the same stop, take-profit and time stop, whether it traded or not. "
               "This is how we check that the gates cause better outcomes rather than just fewer trades.</p>"
               "<div class=scroll><table><tr><th>Group</th><th class=num>Cases</th><th class=num>Avg hypothetical return</th>"
               "<th class=num>Hit rate</th></tr>")
    rows = [("Opened by the agent", gates["opened"]), ("Skipped (any reason)", gates["skipped"])]
    rows += [(f"Skipped: {g.replace('_',' ')}", v) for g, v in gates["skipped_by_gate"].items()]
    for name, st in rows:
        if not st.get("n"):
            continue
        out.append(f"<tr><td>{E(name)}</td><td class=num>{st['n']}</td><td class='num {_cls(st['avg_ret'])}'>"
                   f"{_pct(st['avg_ret'])}</td><td class=num>{st['hit_rate']*100:.0f}%</td></tr>")
    out.append("</table></div></div>")

    # voices
    graded = {}
    for r in recs:
        if r["kind"] == "trust_update":
            g = graded.setdefault(r["voice"], [0, 0])
            g[0] += r["correct"]
            g[1] += 1
    out.append("<h2>Voices and earned trust</h2><div class=card><p class=sub>Trust starts at the user's weight "
               f"and moves with each call graded {agent.cfg['signal']['maturity_h']} h later "
               "(Beta posterior on correct direction).</p><div class=scroll><table><tr><th>Voice</th><th>Source</th>"
               "<th class=num>User weight</th><th class=num>Calls graded</th><th class=num>Correct</th><th class=num>Trust now</th></tr>")
    src = {v["handle"]: v["source"] for v in agent.cfg["voices"]}
    for v in sorted(agent.weight, key=lambda x: -agent.trust(x)):
        c, n = graded.get(v, [0, 0])
        out.append(f"<tr><td>{E(v)}</td><td>{E(src.get(v,''))}</td><td class=num>{agent.weight[v]}</td>"
                   f"<td class=num>{n}</td><td class=num>{'—' if not n else f'{c/n*100:.0f}%'}</td>"
                   f"<td class=num>{agent.trust(v)}</td></tr>")
    out.append("</table></div></div>")

    out.append("<h2>Paper equity</h2><div class=card>" + _equity_svg(agent.equity_curve) + "</div>")
    out.append("<h2>User-defined risk limits</h2><div class=card><pre>" +
               E(json.dumps({"signal": agent.cfg["signal"], "market": agent.cfg["market"], "risk": risk}, indent=2)) + "</pre></div>")
    out.append("<h2>Reproduce</h2><div class=card><pre>git clone https://github.com/Erehemoc/chorus-kol-agent\n"
               "cd chorus-kol-agent\npython -m chorus.cli replay   # same inputs → identical hash chain\n"
               "python -m chorus.cli verify out/trail.jsonl\npython -m chorus.cli collect --days 14   # fresh public data</pre>"
               "<p class=sub>Not financial advice. Practice positions only; the project contains no exchange or "
               "order code. Sources are public Telegram channel previews; X (official API) and Farcaster "
               "adapters are included.</p></div>")
    out.append("</div></body></html>")
    return "".join(out)
