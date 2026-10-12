# The Bouncer

A read-only follower-health scanner for X. Once a month (or whenever you say "scan now") it takes a snapshot of your followers and the accounts you follow, compares it with the last one, and writes a **private** report:

- **New followers**: which look real and which are likely bots
- **Who left** since the last scan, plus the posts you put out in that window
- **Top 10 real engagers** (replies, quotes, mentions)
- **Likely bots**: handle + the reasons. Always "suspected", never "confirmed". An account is flagged only when 3+ signals overlap (under 50 followers, following 1,000+, 0 posts, digit-heavy handle, default avatar, promo/crypto bio, account under 30 days old)
- **Dead follows**: accounts you follow that haven't posted in 90+ days

People who replied to, quoted or mentioned you in the last 90 days are never flagged, and neither is anyone on your protect list (handles, or hashtags in bios for campaigns, ARGs and events).

**You make every removal decision by hand.** The Bouncer only reads and reports.

## What it will never do
- Follow, unfollow, block, mute, like, post, reply or DM. The client refuses any non-GET request and any endpoint outside a 5-item allowlist (`bouncer/xclient.py`, `guard()`), and the tests check it.
- Control x.com through a browser, or scrape.
- Post or share your report anywhere. Reports are written locally, readable only by you (file mode 600).
- Use anyone else's keys. There are no shared keys: you create your own app and pay for your own credits.

The Bouncer is an independent community project. It isn't made, endorsed or supported by X.

## Costs
It uses X's pay-per-use API. When the app belongs to you and you read your own data, X charges the **owned-read rate: $0.001 per item returned** (each follower, each followed account, each mention, each of your posts). Add about $0.01 for the one profile lookup per run.

Estimated cost of one full scan:

| Followers | Following | Mentions (90 days, max 800) | Your posts (90 days, max 3,200) | Items | Per scan |
|---|---|---|---|---|---|
| 1,000 | 500 | 100 | 300 | 1,900 | ~$1.91 |
| 4,000 | 2,000 | 300 | 1,900 | 8,200 | ~$8.21 |
| 10,000 | 2,000 | 800 | 3,200 | 16,000 | ~$16.01 |
| 50,000 | 3,000 | 800 | 3,200 | 57,000 | ~$57.01 |

Monthly cost = per scan × scans per month (weekly ≈ 4.33, monthly 1, quarterly ⅓). For most accounts, monthly is plenty.

- `setup` and `estimate` show **your** numbers from your real follower/following counts before anything is scanned, and the scan refuses to run if the projected monthly cost is over your cap.
- X doesn't charge twice for the same item read within the same UTC day (it calls this a soft guarantee), so re-running a failed scan the same day costs little extra.
- Prices are X's and can change. Check console.x.com, and update `owned_read_rate_usd` in your config if they do.

## Setup (about 10 minutes)

### 1. In console.x.com (about 5 minutes)
1. Sign in at https://console.x.com with the X account you want to scan.
2. **Create a Project** (the Production label is fine), then **create an app inside it**. A standalone app gets `403 client-not-enrolled`.
3. User authentication settings → App permissions: **Read only**. Don't enable write or DMs.
4. Keys and tokens: copy the **API Key** and **API Key Secret**, then generate the **Access Token** and **Access Token Secret** for your account. Don't use the Bearer Token. The token should say "Read only".
   - **Regenerate gotcha:** regenerating replaces the API Key and Secret *together*, and can cancel older access tokens. If you regenerate, copy both again and generate the Access Token afterward.
5. Billing: load pay-per-use credits (or add a card), **set a monthly spending limit**, and **turn auto-recharge off** so the limit is a hard stop.

### 2. On your computer
```bash
pip install -r requirements.txt          # only PyYAML
export X_API_KEY=... X_API_SECRET=... X_ACCESS_TOKEN=... X_ACCESS_TOKEN_SECRET=...
python3 -m bouncer setup                 # handle, cap, cadence -> config.yaml, then cost estimate
python3 -m bouncer scan                  # first snapshot + report
```
Keep your keys in your shell or a password manager. Don't put them in a file in this folder, and never paste them into a chat. Using Grok Bot? See `SKILL.md`. It asks for your keys through masked secret boxes.

### Troubleshooting
- **403 client-not-enrolled**: the app isn't in a Project, or the account has no credits. Fix both and run setup again.
- **401 Unauthorized**: a key was regenerated after you copied it. See the regenerate gotcha above.
- **429 / 5xx**: rate limit or a hiccup at X. The scanner backs off, keeps what it has already pulled, and logs the exact status.

## Commands
- `python3 -m bouncer setup [--handle H --cap 10 --cadence monthly --non-interactive]`
- `python3 -m bouncer estimate`: 1 lookup (~$0.01). Exits with code 2 if over the cap.
- `python3 -m bouncer scan`: estimate → refuse if over cap → snapshot `snapshots/DATE.json` + report `reports/DATE.md`
- `python3 -m bouncer report [snapshot]`: rebuild a report offline (no API calls)
- Tests: `python3 tests/test_bouncer.py` (fixtures only)

## Configuration
Everything user-specific lives in `config.yaml` (copied from `config.example.yaml`): handle, monthly cap, cadence, report day, protect list, bot-signal thresholds and keywords, inactivity window (90), and engagement-protect window (90). There are no secrets in it.

## Endpoints used (OAuth 1.0a user context, GET only)
`GET /2/users/by/username/:handle`, `GET /2/users/:id/followers`, `/following`, `/mentions`, `/tweets` (your own id only).

Known limit: a quote of your post counts toward protection only if it also @-mentions you. Catching every quote would take a pricier, non-owned endpoint.

## Compliance notes
- Each user runs their **own** developer app with their own credits. Don't share keys, and don't run scans on someone else's behalf with your keys or theirs.
- Don't redistribute the data the scan pulls. X's Developer Agreement limits sharing user data with third parties, and the report is meant for you alone.
- Follow X's Developer Agreement and Policy. This is not legal advice.

## License
MIT. Use it, fork it, keep it read-only.
