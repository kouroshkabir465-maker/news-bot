#!/bin/bash
# Rotate @kourosh_news_bot token after BotFather /revoke.
# usage: put the NEW token alone in a file (chmod 600), then:  tools/update_token.sh /path/to/token_file
# Updates: GitHub secret NEWS_BOT_TOKEN, Cloudflare worker secret NEWS_BOT_TOKEN, re-sets the Telegram webhook (same secret header).
# Needs on the box: gh login, $CLOUDFLARE_API_TOKEN, /workspace/.news_webhook_secret. Never prints the token.
set -euo pipefail
F="$1"; T=$(tr -d ' \n\r' < "$F"); SEC=$(cat /workspace/.news_webhook_secret)
A=c85d54bb2b5d061be7bac87bd61074b7; R=kouroshkabir465-maker/news-bot
curl -sf "https://api.telegram.org/bot$T/getMe" > /dev/null || { echo "token invalid"; exit 1; }
printf %s "$T" | gh secret set NEWS_BOT_TOKEN -R $R && echo "github secret updated"
python3 -c 'import json,sys;print(json.dumps({"name":"NEWS_BOT_TOKEN","text":sys.stdin.read(),"type":"secret_text"}))' <<< "$T" | sed 's/\\n"/"/' > /tmp/nb.json
curl -sf -X PUT -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "content-type: application/json" \
  "https://api.cloudflare.com/client/v4/accounts/$A/workers/scripts/news-bot-webhook/secrets" --data @/tmp/nb.json -o /dev/null && echo "worker secret updated"; rm -f /tmp/nb.json
curl -s "https://api.telegram.org/bot$T/setWebhook" -d url=https://news-bot-webhook.kourosh-gold.workers.dev -d secret_token="$SEC" \
  -d 'allowed_updates=["message","edited_message"]' | grep -o '"ok":[a-z]*'
shred -u "$F" 2>/dev/null || rm -f "$F"; echo "token file removed"
