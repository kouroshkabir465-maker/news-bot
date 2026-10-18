# News bot
Farsi digest of important Iran/USA news (Iran International, Fox News, Bloomberg, CNN, Politico, NY Post) to Telegram, 09:00/15:00/21:00 Istanbul via GitHub Actions.
Realtime: `alert.yml` (every 10 min via the news-bot-webhook Cloudflare cron, GitHub cron 17/47 as backup) sends each NEW important item as ⚡ فوری, max 5 per run; shares `seen.json` dedupe with the digest. State pushes merge (tools/push_state.sh).
