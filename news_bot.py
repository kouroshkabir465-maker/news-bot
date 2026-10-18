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
KB = json.dumps({"keyboard": [[{"text": "🔍 بررسی کن"}]], "resize_keyboard": True, "is_persistent": True})
REPLY = "--reply" in sys.argv
FEEDS = [  # (source name, url, language)
    ("ایران اینترنشنال", "https://www.iranintl.com/feed", "fa"),
    ("Fox News", "https://moxie.foxnews.com/google-publisher/world.xml", "en"),
    ("Fox News", "https://moxie.foxnews.com/google-publisher/politics.xml", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/politics/news.rss", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/news.rss", "en"),
    ("Bloomberg", "https://feeds.bloomberg.com/economics/news.rss", "en"),
    ("Fox News", "https://moxie.foxnews.com/google-publisher/latest.xml", "en"),
    ("New York Post", "https://nypost.com/feed/", "en"),
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
         (r"talks|negotiat|deal|diplomac|مذاکر|توافق|دیپلما", 2), (r"protest|execution|arrest|اعتراض|اعدام|بازداشت", 1)]
USONLY = [(r"trump|white house|congress|senate|supreme court|pentagon|federal reserve|\bfed\b|ترامپ|کاخ سفید|کنگره", 2),
          (r"sanction|tariff|war|missile|shutdown|election|economy|inflation|تحریم|تعرفه", 1)]

PAHLAVI = r"pahlavi|پهلوی|شاهزاده رضا"
TURKEY = r"turkey|türkiye|turkiye|turkish|erdogan|erdoğan|ankara|istanbul|\blira\b|ترکیه|اردوغان|آنکارا|استانبول|لیر"
TR_TOPIC = [(r"erdogan|erdoğan|اردوغان", 2), (r"election|parliament|court|central bank|interest rate|\blira\b|inflation|imamoglu|İmamoğlu|pkk|kurd|syria|nato|opposition|انتخابات|مجلس|دادگاه|بانک مرکزی|نرخ بهره|لیر|تورم|امام‌اوغلو|امام اوغلو|کرد|سوریه|ناتو|مخالفان", 2)]
TRIVIA = r"thanksgiving|recipe|roast turkey|turkey dinner|tourist|vacation|travel guide|celebrity"
SPORT = r"فوتبال|کشتی|والیبال|باشگاه|لیگ|دروازه‌بان|هافبک|مدال|football|soccer|wrestl|world cup|olympic|\bnba\b|\bnfl\b"
def score(text):
    t = text.lower()
    if re.search(SPORT, t): return 0
    s = lambda rules: sum(w for p, w in rules if re.search(p, t))
    if re.search(PAHLAVI, t) and not re.search(TRIVIA, t): return 7 + s(TOPIC)   # Prince Reza Pahlavi
    ir = s(IRAN)
    if ir: return ir + s(TOPIC) if s(TOPIC) >= 2 else 0   # Iran + a politics/security/economy topic
    if re.search(TURKEY, t) and not re.search(TRIVIA, t):
        tr_ = s(TOPIC) + s(TR_TOPIC)
        if tr_ >= 2: return 4 + tr_                       # Turkey politics/economy/security
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
        for blk in re.findall(r"<url>(.*?)</url>", r.text, re.S):
            m = re.search(r"<loc>(.*?)</loc>.*?<news:publication_date>(.*?)</news:publication_date>.*?<news:title>(.*?)</news:title>", blk, re.S)
            if not m: continue
            loc, date, title = m.groups(); im = re.search(r"<image:loc>(.*?)</image:loc>", blk)
            try: ts = dt.datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp()
            except Exception: continue
            if "/video/" in loc: continue
            out.append(dict(src=name, lang=lang, title=clean(title), summary="", link=loc.strip(), ts=ts, img=html.unescape(im.group(1)) if im else ""))
    else:
        for e in feedparser.parse(r.content).entries:
            p = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(p) if p else time.time()
            out.append(dict(src=name, lang=lang, title=clean(e.get("title")), summary=clean(e.get("summary"), 260),
                            link=e.get("link", ""), ts=ts, img=rss_img(e)))
    out = [x for x in out if x["ts"] >= since and x["title"]]
    print(f"feed ok {name:20s} {len(out):3d} recent  {url}")
    return out

from urllib.parse import unquote
def rss_img(e):
    for k in ("media_content", "media_thumbnail"):
        for m in e.get(k) or []:
            if m.get("url"): return unquote(m["url"]) if "%2F" in m["url"] else m["url"]
    for l in e.get("links", []):
        if l.get("rel") == "enclosure" and str(l.get("type", "image")).startswith("image"): return unquote(l["href"]) if "%2F" in l["href"] else l["href"]
    return ""

def og_img(url):
    try:
        t = requests.get(url, headers=UA, timeout=12).text[:300000]
        m = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)', t) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image', t)
        return html.unescape(m.group(1)) if m else ""
    except Exception: return ""

def tr(text):
    """Free translation en->fa: Google gtx endpoint, then MyMemory; fallback None (keep English)."""
    if not text: return ""
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single", timeout=15,
                         params=dict(client="gtx", sl="en", tl="fa", dt="t", q=text[:1500]), headers=UA)
        if r.ok and r.text.startswith("["): USED["google"] += 1; return "".join(p[0] for p in r.json()[0] if p[0]).strip()
    except Exception: pass
    try:
        j = requests.get("https://api.mymemory.translated.net/get", timeout=15, params={"q": text[:480], "langpair": "en|fa"}).json()
        t = j.get("responseData", {}).get("translatedText")
        if j.get("responseStatus") == 200 and t and "MYMEMORY" not in t.upper(): USED["mymemory"] += 1; return t
    except Exception: pass
    USED["english"] += 1; return None
USED = {"google": 0, "mymemory": 0, "english": 0}

def norm(t): return re.sub(r"[^a-z0-9\u0600-\u06ff ]", "", t.lower())[:70]

def main():
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    now = time.time(); since = now - 14 * 3600
    seen = {k: v for k, v in seen.items() if now - v < 4 * 86400}
    if REPLY: since = now - 24 * 3600
    elif now - seen.get("_last_digest", 0) < 2 * 3600 and not os.environ.get("FORCE"):
        print("digest already sent in the last 2h (worker cron + GitHub cron backup), skip"); return
    items = [x for f in FEEDS for x in fetch(*f, since)]
    for x in items:
        x["key"] = hashlib.md5((x["link"].split("?")[0] or x["title"]).encode()).hexdigest()
        x["score"] = score(x["title"] + " " + x["summary"])
    pool, titles = [], set()
    order = (lambda x: -x["ts"]) if REPLY else (lambda x: (-x["score"], -x["ts"]))
    for x in sorted(items, key=order):
        if x["score"] < 5 or (x["key"] in seen and not REPLY) or norm(x["title"]) in titles: continue
        titles.add(norm(x["title"])); pool.append(x)
    pool = pool[:12]
    if not pool and not REPLY: print("no new important items"); return
    now_l = dt.datetime.now(TZ)
    part = "صبح" if now_l.hour < 12 else ("ظهر" if now_l.hour < 18 else "شب")
    head = (f"🔍 <b>آخرین اخبار مهم ایران، آمریکا و ترکیه</b> (۲۴ ساعت اخیر، جدیدترین اول)" if REPLY else
            f"🗞 <b>خلاصهٔ اخبار مهم ایران، آمریکا و ترکیه — {part}</b>") + f"\n📅 {now_l:%Y-%m-%d %H:%M} (استانبول)\n"
    if not pool: head += "\nدر ۲۴ ساعت اخیر خبر مهم تازه‌ای پیدا نشد."
    blocks, imgs = [], []
    for i, x in enumerate(pool, 1):
        if x["lang"] == "fa": t, s = x["title"], x["summary"]
        else:
            t = tr(x["title"]) or x["title"]; s = tr(x["summary"]) if x["summary"] else ""
            if s is None: s = x["summary"]
        b = f"<b>{i}. {html.escape(t)}</b>"
        if s and norm(s)[:40] != norm(t)[:40]: b += f"\n{html.escape(clean(s, 300))}"
        foot = f"\n🕒 {dt.datetime.fromtimestamp(x['ts'], TZ):%Y-%m-%d %H:%M} | 📰 {html.escape(x['src'])} | <a href=\"{html.escape(x['link'], quote=True)}\">لینک خبر</a>"
        if len(b) + len(foot) > 1000:   # caption limit 1024 (after entity parsing); trim summary
            b = f"<b>{i}. {html.escape(clean(t, 200))}</b>" + (f"\n{html.escape(clean(s, 1000 - len(foot) - len(clean(t, 200)) - 60))}" if s else "")
        b += foot
        blocks.append(b); imgs.append(x.get("img") or og_img(x["link"]))
    if DRY:
        print(head); [print(f"[img: {im or '-'}]\n{b}\n") for b, im in zip(blocks, imgs)]; return
    def send(c, method, **d):
        return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", timeout=40, data=dict(
            chat_id=c, parse_mode="HTML", reply_markup=KB, **d)).json()
    ok_any = False
    ask = os.environ.get("TG_CHAT", "").strip()
    for c in (([ask] if ask in CHATS else CHATS[:1]) if REPLY else CHATS):
        j = send(c, "sendMessage", text=head, disable_web_page_preview="true")
        if not j.get("ok"): print(f"send to {c} failed: {j.get('description')}"); continue
        ok_any = True; photos = 0
        for b, im in zip(blocks, imgs):
            if im and send(c, "sendPhoto", photo=im, caption=b).get("ok"): photos += 1; continue
            j = send(c, "sendMessage", text=b, disable_web_page_preview="true")
            if not j.get("ok"): print(f"item send failed: {j.get('description')}")
        print(f"sent to {c}: {len(blocks)} items, {photos} with photo")
    if not ok_any: sys.exit("no recipient received the message")
    if not REPLY:
        for x in pool: seen[x["key"]] = now
        seen["_last_digest"] = now
        json.dump(seen, open(SEEN, "w"))

def welcome(chat):
    j = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", timeout=30, data=dict(chat_id=chat, reply_markup=KB,
        text="سلام داداش 👋 این حساب هم به ربات اخبار وصل شد ✅ خلاصهٔ اخبار مهم ایران، آمریکا و ترکیه هر روز ساعت ۹، ۱۵ و ۲۱ اینجا هم میاد. برای آخرین اخبار دکمهٔ «🔍 بررسی کن» رو بزن.")).json()
    print("welcome:", "ok" if j.get("ok") else j.get("description"))

if __name__ == "__main__":
    if "--welcome" in sys.argv: welcome(sys.argv[sys.argv.index("--welcome") + 1])
    else: main()
