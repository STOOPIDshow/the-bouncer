# Exhibit listing draft

**Name:** The Bouncer

**Tagline:** A read-only follower checkup for your X account. It spots suspected bots and dead follows, and you decide who goes.

**Description:**

The Bouncer is a little monthly checkup for your account. It snapshots your followers and the accounts you follow, compares that with last time, and hands you a private report: new followers (real vs. likely bots), who left, your top 10 real engagers, suspected bots with the exact reasons they were flagged, and accounts you follow that haven't posted in 90+ days. It never removes anyone. Every decision is yours, by hand.

**How it uses the X API.** It runs on your own developer app with OAuth 1.0a user context and Read-only permissions. It only makes GET requests to five endpoints:

- `GET /2/users/by/username/:handle`: one lookup to get your ID and your follower/following counts, so it can show you a cost estimate *before* scanning
- `GET /2/users/:id/followers`: your followers, with the profile fields it needs for the bot signals (follower/following counts, post count, avatar, bio, account age)
- `GET /2/users/:id/following`: who you follow. It reads `most_recent_tweet_id` from that same response to find dead follows, with no extra calls
- `GET /2/users/:id/mentions`: your last 90 days of mentions, so people who've talked to you are protected and never flagged
- `GET /2/users/:id/tweets`: your own recent posts, for the "what went out" section and the engagement context

**What it never does:** follow, unfollow, block, mute, like, post or DM. It doesn't drive x.com in a browser, doesn't scrape, and doesn't share your report anywhere. A built-in guard refuses any non-GET request and any endpoint outside that list. Bots are always "suspected", never "confirmed".

**Pricing for you:** the tool itself is free. You pay X directly with your own credits at the owned-read rate ($0.001 per item). A scan runs about $2 at 1k followers, $8 at 4k, $16 at 10k and $57 at 50k, including mentions and posts. It shows you the estimate first and won't scan if that's over your cap. There are no shared keys: everyone brings their own app.

Made by @xbSTOOPID. It's a community project, not affiliated with X.
