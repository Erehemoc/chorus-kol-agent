"""Post sources. Every source returns a list of Post dicts with the same shape:

    {"id", "source", "voice", "url", "ts" (ISO-8601 UTC), "text"}

Sources:
  * telegram  - public channel web preview (https://t.me/s/<channel>), no login, no key
  * farcaster - public Warpcast API (casts by username), no key
  * x         - official X API v2 (user timeline). Needs X_BEARER_TOKEN; skipped if absent.
  * fixture   - a JSONL file of posts (used for replays, tests and the bundled demo)
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (chorus-kol-agent; research; paper-trading only)"}


def _get(url: str, headers: dict | None = None, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _clean(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"[ \t]+", " ", html.unescape(fragment)).strip()


_TG_MSG = re.compile(
    r'data-post="(?P<post>[^"]+)".*?'
    r'(?:<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<text>.*?)</div>.*?)?'
    r'<time datetime="(?P<ts>[^"]+)"',
    re.S,
)


def parse_telegram(page: str, channel: str) -> list[dict]:
    posts = []
    for m in _TG_MSG.finditer(page):
        text = _clean(m.group("text") or "")
        if not text:
            continue
        post = m.group("post")
        ts = m.group("ts").replace("+00:00", "Z")
        posts.append({"id": f"tg:{post}", "source": "telegram", "voice": channel,
                      "url": f"https://t.me/{post}", "ts": ts, "text": text})
    return posts


def fetch_telegram(channel: str, since_iso: str | None = None, max_pages: int = 30,
                   pause: float = 1.0) -> list[dict]:
    """Walk a public channel backwards with ?before= until `since_iso` or max_pages."""
    out: dict[str, dict] = {}
    before = None
    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        page_posts = parse_telegram(_get(url), channel)
        if not page_posts:
            break
        for p in page_posts:
            out[p["id"]] = p
        oldest = min(page_posts, key=lambda p: p["ts"])
        if since_iso and oldest["ts"] < since_iso:
            break
        nums = [int(p["id"].rsplit("/", 1)[1]) for p in page_posts]
        nxt = min(nums)
        if before is not None and nxt >= before:
            break
        before = nxt
        time.sleep(pause)
    posts = sorted(out.values(), key=lambda p: p["ts"])
    return [p for p in posts if not since_iso or p["ts"] >= since_iso]


def fetch_farcaster(username: str, limit: int = 50) -> list[dict]:
    u = json.loads(_get("https://api.warpcast.com/v2/user-by-username?username="
                        + urllib.parse.quote(username)))
    fid = u["result"]["user"]["fid"]
    data = json.loads(_get(f"https://api.warpcast.com/v2/casts?fid={fid}&limit={limit}"))
    posts = []
    for c in data.get("result", {}).get("casts", []):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["timestamp"] / 1000))
        posts.append({"id": f"fc:{c['hash']}", "source": "farcaster", "voice": username,
                      "url": f"https://warpcast.com/{username}/{c['hash'][:10]}",
                      "ts": ts, "text": c.get("text", "")})
    return sorted(posts, key=lambda p: p["ts"])


def fetch_x(username: str, max_results: int = 50) -> list[dict]:
    """Official X API v2. Requires X_BEARER_TOKEN (a paid X API plan). Returns [] without it."""
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return []
    h = {"Authorization": f"Bearer {token}"}
    u = json.loads(_get(f"https://api.x.com/2/users/by/username/{username}", h))
    uid = u["data"]["id"]
    q = urllib.parse.urlencode({"max_results": max(5, min(100, max_results)),
                                "tweet.fields": "created_at"})
    t = json.loads(_get(f"https://api.x.com/2/users/{uid}/tweets?{q}", h))
    posts = []
    for tw in t.get("data", []):
        ts = tw["created_at"].replace(".000Z", "Z")
        posts.append({"id": f"x:{tw['id']}", "source": "x", "voice": username,
                      "url": f"https://x.com/{username}/status/{tw['id']}",
                      "ts": ts, "text": tw["text"]})
    return sorted(posts, key=lambda p: p["ts"])


def load_fixture(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def fetch_voice(voice: dict, since_iso: str | None = None) -> list[dict]:
    kind, handle = voice["source"], voice["handle"]
    if kind == "telegram":
        return fetch_telegram(handle, since_iso)
    if kind == "farcaster":
        return fetch_farcaster(handle)
    if kind == "x":
        return fetch_x(handle)
    raise ValueError(f"unknown source {kind}")
