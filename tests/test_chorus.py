import json
import pathlib

import pytest

from chorus.engine import Chorus, MAX_VOICES
from chorus.market import Prices
from chorus.nlp import find_tokens, read_post
from chorus.sources import parse_telegram
from chorus.trail import Trail, verify

ROOT = pathlib.Path(__file__).resolve().parents[1]
H = 3600_000


# ---------- reading posts -------------------------------------------------------------
def test_sentiment_is_scoped_per_token():
    r = read_post("BTC and ETH spot ETFs saw net outflows. XRP and ZEC spot ETFs saw net inflows.")
    assert r["calls"]["BTC"]["direction"] == -1
    assert r["calls"]["ZEC"]["direction"] == 1


def test_negation_flips_and_prefix_words_do_not_match():
    assert read_post("$SOL is not bullish at all")["calls"]["SOL"]["direction"] == -1
    assert read_post("Holders of $SOL are waiting longer")["calls"]["SOL"]["direction"] == 0


def test_brand_name_is_not_a_signal():
    r = read_post("Pump fun deposited 129,798 $SOL into Kraken and is dumping again")
    assert r["calls"]["SOL"]["direction"] == -1


def test_digest_posts_are_ignored():
    r = read_post("Movers: $BTC +1% $ETH +2% $SOL +3% $XRP +1% $DOGE +5% rally")
    assert r["digest"] and r["calls"] == {}


def test_ambiguous_tickers_need_cashtag():
    assert "OP" not in find_tokens("OP said the market is quiet")
    assert "OP" in find_tokens("whale bought $OP")


def test_conviction_and_urgency_have_reasons():
    r = read_post("BREAKING 🚨 Smart money bought $ETH right now, massive accumulation")
    assert r["urgency"] > 0.5 and r["conviction"] > 0.5
    assert "breaking" in r["why"]["urgency"]


def test_telegram_parser():
    page = ('<div data-post="chan/12"><div class="tgme_widget_message_text js-message_text">'
            'Whale bought $ETH<br/>again</div><time datetime="2026-10-20T10:00:00+00:00"></time>')
    [p] = parse_telegram(page, "chan")
    assert p["url"] == "https://t.me/chan/12" and p["ts"] == "2026-10-20T10:00:00Z"
    assert "again" in p["text"]


# ---------- trail -------------------------------------------------------------------------
def test_trail_detects_tampering(tmp_path):
    t = Trail({"x": 1})
    t.add("signal", "2026-01-01T00:00:00Z", a=1)
    t.add("signal", "2026-01-01T01:00:00Z", a=2)
    f = tmp_path / "t.jsonl"
    t.dump(str(f))
    assert verify(str(f))[0]
    lines = f.read_text().splitlines()
    lines[1] = lines[1].replace('"a":1', '"a":9')
    f.write_text("\n".join(lines))
    assert not verify(str(f))[0]


# ---------- engine on a synthetic scenario ------------------------------------------------
def _scenario(prices_path=None):
    t0 = 1_760_000_000_000 // H * H
    series = [[t0 + i * H, 100.0 * (1 + 0.004 * max(0, i - 30)), 1e9] for i in range(120)]
    posts = []
    for k, voice in enumerate(["a", "b", "c"]):
        ts = t0 + (30 + k) * H
        import datetime as dt
        iso = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        posts.append({"id": f"x{k}", "source": "fixture", "voice": voice, "url": f"u{k}",
                      "ts": iso, "text": "Whale bought a massive amount of $ETH, bullish"})
    cfg = {"voices": [{"source": "fixture", "handle": v} for v in "abc"]}
    return cfg, posts, {"ETH": series}


def test_convergence_opens_a_practice_position_within_limits():
    cfg, posts, prices = _scenario()
    agent = Chorus(cfg, posts, prices)
    s = agent.run()
    opens = [r for r in agent.trail.records if r["kind"] == "practice_open"]
    assert opens and opens[0]["side"] == "LONG"
    assert opens[0]["size_pct"] <= agent.cfg["risk"]["max_position_pct"]
    assert s["paper_return"] > 0
    conv = next(r for r in agent.trail.records if r["kind"] == "convergence")
    assert conv["decision"] == "OPEN" and len(conv["voices"]) >= 2


def test_single_voice_never_trades():
    cfg, posts, prices = _scenario()
    agent = Chorus(cfg, posts[:1], prices)
    agent.run()
    assert not any(r["kind"] == "practice_open" for r in agent.trail.records)


def test_runs_are_deterministic():
    cfg, posts, prices = _scenario()
    assert Chorus(cfg, posts, prices).run()["trail_head"] == Chorus(cfg, posts, prices).run()["trail_head"]


def test_voice_limit():
    with pytest.raises(ValueError):
        Chorus({"voices": [{"source": "x", "handle": str(i)} for i in range(MAX_VOICES + 1)]}, [], {})


def test_prices_have_no_look_ahead():
    p = Prices({"ETH": [[0, 1.0, 0], [10, 2.0, 0]]})
    assert p.at("ETH", 9)[1] == 1.0 and p.at("ETH", -1) is None


# ---------- bundled real-data demo --------------------------------------------------------
@pytest.mark.skipif(not (ROOT / "data" / "posts.jsonl").exists(), reason="demo data not present")
def test_bundled_demo_replays_to_the_published_head():
    cfg = json.load(open(ROOT / "config.json"))
    posts = [json.loads(x) for x in open(ROOT / "data" / "posts.jsonl")]
    prices = json.load(open(ROOT / "data" / "prices.json"))
    agent = Chorus(cfg, posts, prices)
    s = agent.run()
    stored = [json.loads(x) for x in open(ROOT / "out" / "trail.jsonl")]
    assert stored[-1]["hash"] == s["trail_head"]
    for r in agent.trail.records:
        if r["kind"] == "practice_open":
            assert r["size_pct"] <= agent.cfg["risk"]["max_position_pct"] + 1e-9


def test_project_contains_no_order_code():
    banned = ("ccxt", "create_order", "place_order", "/api/v3/order", "privateKey", "private_key")
    for f in (ROOT / "chorus").glob("*.py"):
        text = f.read_text()
        assert not any(b in text for b in banned), f
