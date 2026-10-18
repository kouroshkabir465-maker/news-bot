#!/bin/bash
# Push seen.json to the 'state' branch. Merges with the remote copy (newest timestamp per key, <4 days)
# and retries, so the digest and the 10-min alert runs never overwrite each other's dedupe state.
set -u
# run from /tmp: checking out the state branch below removes this file from the work tree
[ "$0" = /tmp/push_state.sh ] || { cp "$0" /tmp/push_state.sh; exec bash /tmp/push_state.sh; }
[ -f seen.json ] || exit 0
cp seen.json /tmp/seen_local.json
git config user.name news-bot; git config user.email news-bot@users.noreply.github.com
for i in 1 2 3 4 5; do
  if git fetch -q origin state; then git checkout -qf -B st origin/state; else git checkout -qf --orphan st; git rm -rqf . 2>/dev/null; rm -f seen.json; fi
  python3 - <<'PY'
import json, os, time
loc = json.load(open("/tmp/seen_local.json")); rem = json.load(open("seen.json")) if os.path.exists("seen.json") else {}
now = time.time()
for k, v in rem.items():
    if now - v < 4 * 86400 and v > loc.get(k, 0): loc[k] = v
json.dump(loc, open("seen.json", "w"))
PY
  git add seen.json
  git diff --cached --quiet && { echo "state unchanged"; exit 0; }
  git commit -qm "state $(date -u +%FT%TZ)"
  git push -q origin HEAD:state && { echo "state pushed"; exit 0; }
  echo "push conflict, retry $i"; sleep $((i * 3))
done
echo "state push failed"; exit 1
