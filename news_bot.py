#!/usr/bin/env python3
"""Iran/USA news digest -> Telegram (Farsi). Sources: Iran International, Fox News, Bloomberg, CNN, Politico, NY Post.
  news_bot.py            -> build + send digest of new items, update seen.json
  news_bot.py --dry      -> print only"""
import os, sys, re, json, time, html, hashlib, datetime as dt, calendar, requests, feedparser
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Istanbul")
TOKEN = os.environ.get("NEWS_BOT_TOKEN", "")
CHATS = [c.strip() for c in os.environ.get("NEWS_CHAT_IDS", "8561650547,5728075440").split(",") if c.strip()]
SEEN = os.path.join(HERE, "seen.json")
DRY = "--dry" in sys.argv
UA = {"User-Agent": "Mozilla/5.0 (news-bot)"}
FEEDS = [  # (source name, url, language)
    ("ایران اینترنشنال", "https://www.iranintl.com/feed", "fa"),
    ("Fox News", "https://moxie.foxnews.com/google-publisher/world.xml", "en"),
    ("Fox News", "https://moxie.foxnews.com/google-publisher/politics.xml", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/politics/news.rss", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "en"),
    ("CNN", "https://www.cnn.com/sitemap/news.xml", "en"),   # CNN RSS is dead; news sitemap has titles
    ("Politico", "https://rss.politico.com/politics-news.xml", "en"),
    ("Politico", "https://rss.politico.com/defense.xml", "en"),
    ("New York Post", "https://nypost.com/world-news/feed/", "en"),
    ("New York Post", "https://nypost.com/politics/feed/", "en"),
]
# relevance: (regex, weight). Iran terms are required; US/topic terms boost.
IRAN = [(r"\biran\w*|tehran|khamenei|irgc|revolutionary guard|pezeshkian|araghchi|hormuz|ایران|تهران|خامنه|سپاه|پزشکیان|عراقچی|هرمز", 5)]
TOPIC = [(r"sanction|تحریم", 3), (r"nuclear|uranium|enrich|iaea|هسته|اورانیوم|غنی|آژانس", 3),
         (r"\bwar\b|strike|attack|missile|drone|military|israel|جنگ|حمله|موشک|پهپاد|نظامی|اسرائیل", 2),
         (r"trump|white house|washington|state department|pentagon|congress|u\.s\.|\bus\b|united states|america|آمریکا|ترامپ|واشنگتن|کاخ سفید", 2),
         (r"oil|economy|rial|inflation|tariff|نفت|اقتصاد|ریال|تورم|دلار", 2),
         (r"talks|negotiat|deal|diplomac|مذاکره|توافق|دیپلما", 2), (r"protest|execution|arrest|اعتراض|اعدام|بازداشت", 1)]
USONLY = [(r"trump|white house|congress|senate|supreme court|pentagon|federal reserve|\bfed\b|ترامپ|کاخ سفید|کنگره", 2),
          (r"sanction|tariff|war|missile|shutdown|election|economy|inflation|تحریم|تعرفه", 1)]

SPORT = r"فوتبال|کشتی|والیبال|باشگاه|لیگ|دروازه‌بان|هافبک|مدال|football|soccer|wrestl|world cup|olympic|\bnba\b|\bnfl\b"
def score(text):
    t = text.lower()
    if re.search(SPORT, t): return 0
    s = lambda rules: sum(w for p, w in rules if re.search(p, t))
    ir = s(IRAN)
    if ir: return ir + s(TOPIC) if s(TOPIC) >= 2 else 0   # Iran + a politics/security/economy topic
    us = s(USONLY)
    return us if us >= 3 else 0   # strong US politics/economy stories without Iran

def clean(x, n=None):
    x = html.unescape(re.sub(r"<[^>]+>", " ", x or "")); x = re.sub(r"\s+", " ", x).strip()
    if n and len(x) > n: x = x[:n].rsplit(" ", 1)[0] + "…"
    return x

def fetch(name, url, lang, since):
    try:
        r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
    except Exception as e:
        print(f"FEED FAIL {name} {url}: {e}"); return []
    out = []
    if "sitemap" in url:   # CNN news sitemap
        for loc, date, title in re.findall(r"<loc>(.*?)</loc>.*?<news:publication_date>(.*?)</news:publication_date>.*?<news:title>(.*?)</news:title>", r.text, re.S):
            try: ts = dt.datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp()
            except Exception: continue
            if "/video/" in loc: continue
            out.append(dict(src=name, lang=lang, title=clean(title), summary="", link=loc.strip(), ts=ts))
    else:
        for e in feedparser.parse(r.content).entries:
            p = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(p) if p else time.time()
            out.append(dict(src=name, lang=lang, title=clean(e.get("title")), summary=clean(e.get("summary"), 260),
                            link=e.get("link", ""), ts=ts))
    out = [x for x in out if x["ts"] >= since and x["title"]]
    print(f"feed ok {name:20s} {len(out):3d} recent  {url}")
    return out

def tr(text):
    """Free translation en->fa: Google gtx endpoint, then MyMemory; fallback None (keep English)."""
    if not text: return ""
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single", timeout=15,
                         params=dict(client="gtx", sl="en", tl="fa", dt="t", q=text[:1500]), headers=UA)
        if r.ok and r.text.startswith("["): return "".join(p[0] for p in r.json()[0] if p[0]).strip()
    except Exception: pass
    try:
        j = requests.get("https://api.mymemory.translated.net/get", timeout=15, params={"q": text[:480], "langpair": "en|fa"}).json()
        t = j.get("responseData", {}).get("translatedText")
        if j.get("responseStatus") == 200 and t and "MYMEMORY" not in t.upper(): return t
    except Exception: pass
    return None

def norm(t): return re.sub(r"[^a-z0-9\u0600-\u06ff ]", "", t.lower())[:70]

def main():
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    now = time.time(); since = now - 14 * 3600
    seen = {k: v for k, v in seen.items() if now - v < 4 * 86400}
    items = [x for f in FEEDS for x in fetch(*f, since)]
    for x in items:
        x["key"] = hashlib.md5((x["link"].split("?")[0] or x["title"]).encode()).hexdigest()
        x["score"] = score(x["title"] + " " + x["summary"])
    pool, titles = [], set()
    for x in sorted(items, key=lambda x: (-x["score"], -x["ts"])):
        if x["score"] < 5 or x["key"] in seen or norm(x["title"]) in titles: continue
        titles.add(norm(x["title"])); pool.append(x)
    pool = pool[:10]
    if not pool: print("no new important items"); return
    now_l = dt.datetime.now(TZ)
    part = "صبح" if now_l.hour < 12 else ("ظهر" if now_l.hour < 18 else "شب")
    head = f"🗞 <b>خلاصهٔ اخبار مهم ایران و آمریکا — {part}</b>\n📅 {now_l:%Y-%m-%d %H:%M} (استانبول)\n"
    blocks = []
    for i, x in enumerate(pool, 1):
        if x["lang"] == "fa": t, s = x["title"], x["summary"]
        else:
            t = tr(x["title"]) or x["title"]; s = tr(x["summary"]) if x["summary"] else ""
            if s is None: s = x["summary"]
        b = f"<b>{i}. {html.escape(t)}</b>"
        if s and norm(s)[:40] != norm(t)[:40]: b += f"\n{html.escape(clean(s, 300))}"
        b += f"\n📰 {html.escape(x['src'])} | <a href=\"{html.escape(x['link'], quote=True)}\">لینک خبر</a>"
        blocks.append(b)
    msgs, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > 3900: msgs.append(cur); cur = ""
        cur += "\n" + b + "\n"
    msgs.append(cur)
    if DRY:
        print("\n----\n".join(msgs)); return
    ok_any = False
    for c in CHATS:
        for m in msgs:
            j = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", timeout=30, data=dict(
                chat_id=c, text=m, parse_mode="HTML", disable_web_page_preview="true")).json()
            if not j.get("ok"): print(f"send to {c} failed: {j.get('description')}"); break
        else: ok_any = True; print(f"sent to {c}")
    if ok_any:
        for x in pool: seen[x["key"]] = now
        json.dump(seen, open(SEEN, "w"))
    else: sys.exit("no recipient received the digest")

if __name__ == "__main__": main()
