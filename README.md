# Chorus: Multi-KOL Narrative Agent (paper trading only)

**Live report:** https://erehemoc.github.io/chorus-kol-agent/ · **Demo video:** [docs/chorus-demo.mp4](docs/chorus-demo.mp4)

Chorus watches up to **20 market voices you choose**. It reads each post, finds the tokens mentioned, and scores sentiment, **conviction** and **urgency**. It notices when **trusted voices converge** on the same token and direction, and checks whether the market agrees. Then it records the **practice position** it would take under **your risk limits**. Every step is written to a **SHA-256 hash-chained trail**, so a run can be replayed and verified record by record.

> Built for the BLI Legal Tech Hackathon 2, **Autonomous Agents** bounty (RYO-CHAN), "Special Project Spotlight: Multi-KOL Narrative Agent".
> **No real money.** There is no exchange connector and no order code in this repository. A test checks this.

## What happens to a post

```
post ─▶ tokens (cashtags, names) ─▶ per-token sentiment (only the clauses that mention the token)
     ─▶ conviction (certainty vs hedging) ─▶ urgency (breaking, now, 🚨, caps)
     ─▶ signal weighted by the voice's TRUST (graded 24 h later against the real price move)
     ─▶ CONVERGENCE: ≥2 distinct voices, same token + side, within 12 h, score ≥ threshold, weak opposition
     ─▶ MARKET CHECK: price not already moving against the narrative (>3%) and not priced in (>8%)
     ─▶ RISK LIMITS: max position, max total exposure, max open positions, cooldown, shorts on or off
     ─▶ PRACTICE POSITION with stop, take-profit and time stop ─▶ close ─▶ trust update
```

Each arrow is a record in `out/trail.jsonl`. Here is an example record for one decision (shortened):

```json
{"kind":"convergence","token":"ETH","direction":-1,"score":1.0714,
 "voices":{"lookonchainchannel":{"part":0.44,"url":"https://t.me/lookonchainchannel/…"}, "...": "..."},
 "checks":{"distinct_voices":[3,2,true],"score":[1.07,1.0,true],"opposition":[0,0.54,true],
           "market_not_against":[0.0013,-0.03,true],"not_priced_in":[0.0013,0.08,true],
           "cooldown":[null,12,true],"exposure":[535.7,3000.0,true]},
 "decision":"OPEN","prev":"…","hash":"efb9e8dee46a…"}
```

The `practice_open` record that follows links back to this record by hash (`because`). The matching `practice_close` links to the open record (`opened_by`).

## Bundled run on real public data (Oct 10–24, 2026)

- **Voices:** 13 public Telegram channels: on-chain analysts (Lookonchain, Spot On Chain, ai_9684xtpa), research desks (CryptoQuant, Glassnode), and newsrooms (Wu Blockchain, The Block, Cointelegraph, Watcher Guru and others).
- **Prices:** hourly series from CoinGecko for 24 tokens.
- **Results:** 1,167 posts produced 272 token calls, 137 convergence checks and 11 practice trades. Paper P&L was −0.58% on $10,000, with a win rate of 50% on closed trades.
- **Gate check:** the report replays every convergence the agent *skipped* with the same exits. Convergences filtered out by the score gate went the right way 30% of the time, and the cooldown rejects 20%, against 56% for the trades it opened. The average hypothetical return of the opened trades (−0.94%) was no better than that of the score-gate rejects (−0.93%), because one stop-loss dominated a small sample.

The result is reported as it came out. The goal is an agent whose decisions you can audit, not a claim about returns.

## Run it

Requirements: Python 3.10+, standard library only. Install `pytest` to run the tests.

```bash
python -m chorus.cli replay                      # re-run on the bundled frozen inputs -> identical chain
python -m chorus.cli verify out/trail.jsonl      # tamper check
python -m chorus.cli report --out docs/index.html
python -m chorus.cli collect --days 14           # fresh public data for the voices in config.json
python -m chorus.cli watch --interval 900        # live loop; every cycle saves a replayable snapshot
python -m pytest -q                              # 15 tests
```

`config.json` holds the voices (max 20; each has a source, a handle and the user's starting weight) and every threshold and risk limit:

| Limit | Default |
|---|---|
| max position | 10% of equity (scaled down by signal score) |
| max total exposure | 30% |
| max open positions | 3 |
| stop loss / take profit | 4% / 8% |
| time stop | 48 h |
| cooldown per token | 12 h |
| shorts | allowed (switch off with `allow_short`) |

## Sources

| Source | Status |
|---|---|
| Telegram public channels (`t.me/s/<channel>`) | used in the demo; no login or key |
| X (official API v2) | `sources.fetch_x`; needs your `X_BEARER_TOKEN` (X API access is paid), skipped without it |
| Farcaster (public Warpcast API) | `sources.fetch_farcaster` |
| Fixture JSONL | replays and tests |

## Why every decision can be checked

- **Same inputs give the same trail.** The reading of a post is rule-based, with no model calls, and the genesis record stores hashes of the posts, prices and config.
- **No look-ahead.** Prices are read at or before the decision time. A test covers this.
- **Trust is earned.** Every call is graded against the real 24-hour price move, and the trail stores before and after values.
- **Tamper evident.** Changing, dropping or reordering a record breaks the chain (`verify`).

## Limits

- The rule-based reading of posts is simple: it can miss sarcasm and the context of long threads. It was chosen because it is transparent and replayable. An LLM reader could be added as another scorer, as long as its outputs are stored in the trail.
- The Telegram channels in the demo are mostly analysts and newsrooms rather than individual influencers. With an X API key, the same pipeline runs on individual X accounts.
- This is a research and teaching tool. Practice positions are not advice.

Built with AI assistance (Claude). MIT licensed.
