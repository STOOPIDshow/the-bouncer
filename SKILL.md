---
name: the-bouncer
description: Read-only X follower-health scanner. Sets up the user's own read-only X app, estimates the cost before scanning, runs a monthly snapshot and writes a private report covering new followers, who left, top engagers, suspected bots and dead follows, plus a linked-handles list. It never follows, unfollows, blocks, mutes, posts or DMs.
---

# The Bouncer (Grok Bot skill)

Use this when the user wants a follower checkup, bot scan, "who unfollowed me", or dead-follows list for **their own** X account.

## Hard rules (never break)
- **GET only.** Use only `python3 -m bouncer` and its read-only client. Never call follow, unfollow, block, mute, like, post, reply or DM endpoints through any tool, connector or script.
- **No browser control of x.com.** No scraping, no clicking through profiles.
- **"Suspected", never "confirmed".** Present bot flags as signals, not verdicts.
- **The user makes every removal decision by hand.** Never offer to remove anyone for them.
- **No shared keys.** Each user brings their own developer app and credits. Never use your own keys, another user's keys, or a hosted app.
- **Keys only through masked secret requests.** Never ask the user to paste a key in chat, and never echo, log or write a key into a file in the repo. If a key shows up in chat anyway, tell the user to regenerate it.
- **The report is private.** Never post it or send it to anyone except the user.

## 1. Setup (target: 10 minutes)
0. Install the tested code (Python 3.9+):
   ```
   git clone https://github.com/STOOPIDshow/the-bouncer.git && cd the-bouncer && pip install -r requirements.txt
   ```
   No git? Download https://github.com/STOOPIDshow/the-bouncer/archive/refs/heads/main.zip, unzip it, `cd` into the folder and run `pip install -r requirements.txt`. Run every `python3 -m bouncer` command from inside that folder.
1. Walk the user through console.x.com (see README "Setup"): create a Project, create the app inside it, set permissions to Read only, then get the API Key + Secret and generate the Access Token + Secret (**not** the Bearer Token). Have them set a monthly spending limit with auto-recharge off.
   - Warn them about the regenerate gotcha: regenerating replaces the key and secret together. If they regenerate, collect both again and have them generate the access token afterward.
2. Collect the four values **one at a time** with masked secret requests, stored as env vars: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
3. Ask for their handle, monthly cap (USD) and cadence (default **monthly**; weekly only for fast-growing accounts or a bot wave), plus any protect handles/hashtags. Then run:
   `python3 -m bouncer setup --handle H --cap C --cadence monthly --non-interactive`
   Add protect entries and threshold tweaks to `config.yaml` if the user wants them.
4. Setup runs the cost estimate (1 lookup, ~$0.01) **before any scan**. Tell the user the per-scan and monthly cost in plain dollars.
   - Exit 2 = over the cap. Don't scan. Offer to raise the cap or slow the cadence.
   - Exit 3 with `client-not-enrolled` = attach the app to a Project and load credits, then retry. 401 = regenerated keys, so collect them again.

## 2. Scan
- Run `python3 -m bouncer scan`. It re-checks the cap itself. Expect a few minutes for large accounts; it backs off on 429s.
- If it fails, report the exact HTTP status it logged. Same-UTC-day re-runs are mostly deduped by X.
- Tell the user the approximate cost from the snapshot's `approx_cost_usd`.

## 3. Deliver
- Summarize `reports/DATE.md` in a few plain sentences: totals, number of suspected bots and top reasons, dead follows, how many were protected, top engagers, and who left (from the second scan on).
- Offer a **linked-handles list**: a Markdown file with every suspected bot (`[@handle](https://x.com/handle)` + reasons) and every dead follow (link + last post date). Build it from the snapshot/report and send it only to the user.
- End by reminding them that removals are theirs to make by hand.

## 4. Reminder routine (spends no credits)
Create a recurring reminder on the user's `report_day` (monthly by default) that **makes no API calls**. It only checks the date of the latest file in `snapshots/` and messages the user something like "It's been N days since your last Bouncer scan (about $X). Want a fresh one?" Run the scan only after they say yes. If the last scan was very recent, skip the message.
