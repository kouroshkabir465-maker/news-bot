// News bot Telegram webhook -> instant ack + repository_dispatch (reply.yml). Separate from gold/scanner bots.
const OWNER = 8561650547;
const EXTRA = [5728075440];   // user's second account
const REPO = "kouroshkabir465-maker/news-bot";
const KB = { keyboard: [[{ text: "🔍 بررسی کن" }]], resize_keyboard: true, is_persistent: true };
const isCheck = t => /^\/check\b|بررسی|^🔍/.test(t.trim());

export default {
  // Cron Trigger 06/12/18 UTC = 09/15/21 Istanbul: on-time digest (GitHub cron stays as backup; bot skips if sent <2h ago)
  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(`https://api.github.com/repos/${REPO}/actions/workflows/digest.yml/dispatches`, {
      method: "POST", body: JSON.stringify({ ref: "main" }),
      headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "news-bot-worker", "content-type": "application/json" },
    }));
  },
  async fetch(req, env, ctx) {
    if (req.method !== "POST") return new Response("ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)
      return new Response("forbidden", { status: 403 });
    let u; try { u = await req.json(); } catch { return new Response("bad", { status: 400 }); }
    const m = u.message || u.edited_message;
    if (!m || !m.chat || (m.chat.id !== OWNER && !EXTRA.includes(m.chat.id))) return new Response("ignored");
    const chat = m.chat.id;
    const text = (m.text || "").slice(0, 200);
    const tg = (method, body) => fetch(`https://api.telegram.org/bot${env.NEWS_BOT_TOKEN}/${method}`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!isCheck(text)) {
      ctx.waitUntil(tg("sendMessage", { chat_id: chat, reply_markup: KB,
        text: "سلام داداش 👋 برای دیدن آخرین اخبار مهم ایران و آمریکا دکمهٔ «🔍 بررسی کن» رو بزن. خلاصهٔ خودکار هم هر روز ساعت ۹، ۱۵ و ۲۱ میاد." }));
      return new Response("ok");
    }
    const ack = tg("sendMessage", { chat_id: chat, text: "در حال بررسی… ⏳", reply_markup: KB,
      reply_parameters: { message_id: m.message_id, allow_sending_without_reply: true } });
    const gh = fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
      method: "POST",
      headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json",
                 "user-agent": "news-bot-worker", "content-type": "application/json" },
      body: JSON.stringify({ event_type: "tg_check", client_payload: { chat, update_id: u.update_id } }),
    }).then(async r => {
      if (r.status >= 300) await tg("sendMessage", { chat_id: chat, text: "⚠️ بررسی شروع نشد، چند دقیقه دیگه دوباره امتحان کن." });
    });
    ctx.waitUntil(Promise.all([ack, gh]));
    return new Response("ok");
  },
};
