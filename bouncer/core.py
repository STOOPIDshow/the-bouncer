"""Estimate, scan, score, diff and report. Read-only: never removes anyone."""
import datetime as dt, glob, json, os, re
from collections import Counter

import yaml

USER_FIELDS = "created_at,description,profile_image_url,public_metrics,most_recent_tweet_id,username,name,protected,verified"
TWEET_FIELDS = "created_at,public_metrics,referenced_tweets,author_id,in_reply_to_user_id,text"
TWITTER_EPOCH_MS = 1288834974657
CADENCE_SCANS_PER_MONTH = {"weekly": 52 / 12, "monthly": 1.0, "quarterly": 1 / 3}


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_t(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def snowflake_time(tweet_id):
    """Post IDs are snowflakes: their creation time is encoded in the ID (free, no API call)."""
    return dt.datetime.fromtimestamp(((int(tweet_id) >> 22) + TWITTER_EPOCH_MS) / 1000, dt.timezone.utc)


# ---------------- estimate ----------------
def lookup_me(client, handle):
    return client.get(f"/2/users/by/username/{handle}", {"user.fields": "public_metrics,created_at"})["data"]


def estimate(client, cfg, me=None):
    me = me or lookup_me(client, cfg["handle"])
    pm = me["public_metrics"]
    rate = cfg["owned_read_rate_usd"]
    posts_cap = 800 + 3200  # worst case: mentions max 800, own posts max 3200
    items = pm["followers_count"] + pm["following_count"]
    per_scan = items * rate
    per_scan_worst = (items + min(posts_cap, pm.get("tweet_count", 0) + 800)) * rate + cfg["user_lookup_rate_usd"]
    cadence = cfg.get("scan_cadence", "monthly")
    if cadence not in CADENCE_SCANS_PER_MONTH:
        raise SystemExit(f"scan_cadence must be one of {sorted(CADENCE_SCANS_PER_MONTH)}, got {cadence!r}")
    monthly = per_scan_worst * CADENCE_SCANS_PER_MONTH[cadence]
    return {
        "handle": me["username"], "user_id": me["id"],
        "followers": pm["followers_count"], "following": pm["following_count"],
        "per_scan_users_usd": round(per_scan, 3), "per_scan_worst_usd": round(per_scan_worst, 3),
        "cadence": cadence, "monthly_usd": round(monthly, 2), "cap_usd": cfg["monthly_spend_cap_usd"],
        "within_cap": monthly <= cfg["monthly_spend_cap_usd"],
    }


def format_estimate(e):
    return (f"@{e['handle']}: {e['followers']:,} followers, {e['following']:,} following\n"
            f"Per full scan (followers+following at owned rate): ${e['per_scan_users_usd']:.2f}\n"
            f"Per scan incl. worst-case mentions/posts + lookup:  ${e['per_scan_worst_usd']:.2f}\n"
            + (f"Projected monthly at {e['cadence']} cadence:").ljust(52) + f"${e['monthly_usd']:.2f}\n" +
            f"Your monthly cap:                                   ${e['cap_usd']:.2f}  -> "
            + ("OK" if e["within_cap"] else "OVER CAP, scan refused"))


# ---------------- scan ----------------
def scan(client, cfg, out_dir="snapshots", now=None):
    now = now or now_utc()
    me = lookup_me(client, cfg["handle"])
    est = estimate(client, cfg, me=me)
    if not est["within_cap"]:
        raise SystemExit(format_estimate(est) + "\nRefusing to scan: projected monthly cost exceeds monthly_spend_cap_usd.")
    uid = me["id"]
    ufields = {"max_results": 1000, "user.fields": USER_FIELDS}
    print("Fetching followers..."); followers, _ = client.paginate(f"/2/users/{uid}/followers", ufields)
    print("Fetching following..."); following, _ = client.paginate(f"/2/users/{uid}/following", ufields)
    tparams = {"max_results": 100, "tweet.fields": TWEET_FIELDS, "expansions": "author_id",
               "user.fields": "username"}
    since_m = now - dt.timedelta(days=cfg["engagement_protect_days"])
    print("Fetching mentions..."); mentions, m_inc = client.paginate(
        f"/2/users/{uid}/mentions", {**tparams, "start_time": iso(since_m)})
    since_p = now - dt.timedelta(days=max(cfg["own_posts_lookback_days"], cfg["posts_report_days"]))
    print("Fetching own posts...")
    try:
        posts, _ = client.paginate(
            f"/2/users/{uid}/tweets", {"max_results": 100, "tweet.fields": TWEET_FIELDS, "start_time": iso(since_p)})
    except RuntimeError as err:  # keep the paid-for data instead of losing it
        os.makedirs(out_dir, exist_ok=True)
        part = os.path.join(out_dir, f"{now:%Y-%m-%d}.partial.json")
        with open(part, "w") as f:
            json.dump({"taken_at": iso(now), "me": me, "followers": followers, "following": following,
                       "mentions": mentions, "posts": None, "error": str(err),
                       "billable_resources": client.resources}, f, indent=1)
        raise RuntimeError(f"{err}\nPartial data saved to {part}") from err
    authors = {u["id"]: u["username"] for u in m_inc.get("users", [])}
    for m in mentions:
        m["author_username"] = authors.get(m.get("author_id"))
    snap = {"taken_at": iso(now), "me": me, "followers": followers, "following": following,
            "mentions": mentions, "posts": posts, "billable_resources": client.resources,
            "approx_cost_usd": round(client.resources * cfg["owned_read_rate_usd"], 3)}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{now:%Y-%m-%d}.json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=1)
    return path, snap


# ---------------- scoring ----------------
def handle_signal(username, sc):
    digits = sum(c.isdigit() for c in username)
    if username and digits / len(username) >= sc["digit_ratio"]:
        return f"digit-heavy handle ({digits}/{len(username)} digits)"
    m = re.search(r"\d+$", username)
    if m and len(m.group()) >= sc["min_trailing_digits"]:
        return f"handle ends in {len(m.group())} digits"
    return None


def bot_signals(u, cfg, now):
    sc = cfg["bot_signals"]
    pm = u.get("public_metrics", {})
    r = []
    if pm.get("followers_count", 0) < sc["max_followers"]:
        r.append(f"under {sc['max_followers']} followers ({pm.get('followers_count', 0)})")
    if pm.get("following_count", 0) > sc["min_following"]:
        r.append(f"following over {sc['min_following']:,} ({pm.get('following_count', 0):,})")
    if sc.get("zero_posts") and pm.get("tweet_count", 0) == 0:
        r.append("0 posts")
    h = handle_signal(u.get("username", ""), sc)
    if h:
        r.append(h)
    if sc.get("default_avatar") and "default_profile_images" in (u.get("profile_image_url") or "default_profile_images"):
        r.append("default avatar")
    bio = (u.get("description") or "").lower()
    hits = [k for k in sc["bio_keywords"] if re.search(r"(?<![a-z0-9])" + re.escape(k.lower()) + r"(?![a-z0-9])", bio)]
    if hits:
        r.append("promo/crypto bio keywords: " + ", ".join(hits[:4]))
    if u.get("created_at"):
        age = (now - parse_t(u["created_at"])).days
        if age < sc["new_account_days"]:
            r.append(f"account {age} days old")
    return r


def engagers(snap, cfg, now):
    since = now - dt.timedelta(days=cfg["engagement_protect_days"])
    c = Counter()
    for m in snap["mentions"]:
        if m.get("created_at") and parse_t(m["created_at"]) >= since and m.get("author_id"):
            c[m["author_id"]] += 1
    return c


def protection(u, cfg, engaged_ids):
    p = cfg.get("protect") or {}
    handles = {h.lower().lstrip("@") for h in p.get("handles") or []}
    if u.get("username", "").lower() in handles:
        return "on protect list"
    bio = (u.get("description") or "").lower()
    for tag in p.get("hashtags") or []:
        t = tag.lower() if tag.startswith("#") else "#" + tag.lower()
        if re.search(re.escape(t) + r"(?![a-z0-9_])", bio):
            return f"bio contains {tag}"
    if u["id"] in engaged_ids:
        return f"replied/quoted/mentioned you in last {cfg['engagement_protect_days']} days"
    return None


def classify(u, cfg, now, engaged_ids):
    reasons = bot_signals(u, cfg, now)
    prot = protection(u, cfg, engaged_ids)
    suspected = len(reasons) >= cfg["bot_signals"]["min_signals_to_flag"] and not prot
    return {"suspected_bot": suspected, "reasons": reasons, "protected": prot}


def last_post_time(u):
    if u.get("most_recent_tweet_id"):
        return snowflake_time(u["most_recent_tweet_id"])
    return None


# ---------------- diff + report ----------------
def previous_snapshot(path, snap_dir="snapshots"):
    files = sorted(f for f in glob.glob(os.path.join(snap_dir, "*.json")) if os.path.abspath(f) != os.path.abspath(path))
    files = [f for f in files if os.path.basename(f) < os.path.basename(path)]
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def period_label(snap, prev):
    if not prev:
        return None
    days = (parse_t(snap["taken_at"]) - parse_t(prev["taken_at"])).days
    return f"since last scan ({prev['taken_at'][:10]}, {days} day{'s' if days != 1 else ''})"


def build_report(snap, prev, cfg, now=None):
    now = now or parse_t(snap["taken_at"])
    period = period_label(snap, prev)
    eng = engagers(snap, cfg, now)
    fol = {u["id"]: u for u in snap["followers"]}
    prev_fol = {u["id"]: u for u in prev["followers"]} if prev else {}
    cls = {uid: classify(u, cfg, now, eng) for uid, u in fol.items()}
    L = [f"# The Bouncer report: @{snap['me']['username']}, {snap['taken_at'][:10]}",
         "", "_Private. Generated from read-only X API data. Nothing was followed, unfollowed, blocked, muted or posted._", "",
         f"Followers: {len(fol):,} | Following: {len(snap['following']):,} | "
         f"Billable items this scan: {snap.get('billable_resources', 0):,} (~${snap.get('approx_cost_usd', 0):.2f})", ""]

    L.append("## New followers" + (f" {period}" if period else ""))
    if not prev:
        L.append("_First snapshot: no previous scan to compare. New-follower and unfollower sections start next run._")
    else:
        new = [fol[i] for i in fol if i not in prev_fol]
        real = [u for u in new if not cls[u["id"]]["suspected_bot"]]
        bots = [u for u in new if cls[u["id"]]["suspected_bot"]]
        L.append(f"{len(new)} new: {len(real)} look real, {len(bots)} suspected bots.")
        L.append("\n**Look real**")
        L += [f"- @{u['username']}" + (f" (protected: {cls[u['id']]['protected']})" if cls[u['id']]['protected'] else "") for u in real] or ["- none"]
        L.append("\n**Suspected bots**")
        L += [f"- @{u['username']}: {'; '.join(cls[u['id']]['reasons'])}" for u in bots] or ["- none"]
    L.append("")

    L.append("## Who left" + (f" {period}" if period else ""))
    if prev:
        gone = [u for i, u in prev_fol.items() if i not in fol]
        L += [f"- @{u['username']}" for u in gone] or ["- nobody"]
        L.append("_Accounts that were suspended, deactivated or went private can also show up here._")
    else:
        L.append("_Needs a previous snapshot._")
    L.append("")

    pdays = (now - parse_t(prev["taken_at"])).days if prev else cfg["posts_report_days"]
    L.append(f"## Posts that went out " + (period if prev else f"in the last {pdays} days"))
    since = parse_t(prev["taken_at"]) if prev else now - dt.timedelta(days=pdays)
    wk = sorted((p for p in snap["posts"] if parse_t(p["created_at"]) >= since), key=lambda p: p["created_at"])
    for p in wk:
        pm = p.get("public_metrics", {})
        txt = " ".join(p.get("text", "").split())[:120]
        L.append(f"- {p['created_at'][:10]} https://x.com/{snap['me']['username']}/status/{p['id']}: \"{txt}\" "
                 f"({pm.get('like_count', 0)} likes, {pm.get('reply_count', 0)} replies, {pm.get('retweet_count', 0)} reposts, {pm.get('quote_count', 0)} quotes)")
    if not wk:
        L.append("- none")
    L.append("")

    L.append(f"## Top {cfg['top_engagers']} real engagers (mentions/replies/quotes, last {cfg['engagement_protect_days']} days)")
    names = {m["author_id"]: m.get("author_username") for m in snap["mentions"]}
    top = [(a, n) for a, n in eng.most_common() if a != snap["me"]["id"] and not (a in cls and cls[a]["suspected_bot"])][: cfg["top_engagers"]]
    for i, (a, n) in enumerate(top, 1):
        tag = "" if a in fol else " (not a follower)"
        L.append(f"{i}. @{names.get(a) or a}: {n} interaction{'s' if n != 1 else ''}{tag}")
    if not top:
        L.append("- none")
    L.append("")

    L.append("## Likely bots among your followers (suspected, not confirmed)")
    sus = sorted((u for u in fol.values() if cls[u["id"]]["suspected_bot"]), key=lambda u: -len(cls[u["id"]]["reasons"]))
    L.append(f"{len(sus)} suspected (flagged at {cfg['bot_signals']['min_signals_to_flag']}+ overlapping signals). "
             "Protected accounts are never listed.")
    L += [f"- @{u['username']} ({len(cls[u['id']]['reasons'])} signals): {'; '.join(cls[u['id']]['reasons'])}" for u in sus] or ["- none"]
    shielded = [u for u in fol.values() if cls[u["id"]]["protected"] and len(cls[u["id"]]["reasons"]) >= cfg["bot_signals"]["min_signals_to_flag"]]
    if shielded:
        L.append("\n_Would have been flagged but are protected:_ " + ", ".join(f"@{u['username']} ({cls[u['id']]['protected']})" for u in shielded))
    L.append("")

    win = cfg["inactivity_window_days"]
    L.append(f"## Dead follows (accounts you follow with no post in {win}+ days)")
    L.append("_Last-post date is decoded from each account's `most_recent_tweet_id` (post IDs embed their timestamp), so it costs nothing beyond the following scan._")
    dead, unknown = [], []
    for u in snap["following"]:
        t = last_post_time(u)
        if t is None:
            (dead if u.get("public_metrics", {}).get("tweet_count", 0) == 0 else unknown).append((u, None))
        elif (now - t).days >= win:
            dead.append((u, t))
    dead.sort(key=lambda x: x[1] or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    for u, t in dead:
        L.append(f"- @{u['username']}: " + (f"last post {t:%Y-%m-%d} ({(now - t).days} days ago)" if t else "has never posted"))
    if not dead:
        L.append("- none")
    if unknown:
        L.append("\n_Last post unknown (field missing, e.g. protected account):_ " + ", ".join("@" + u["username"] for u, _ in unknown))
    L += ["", "---", "**Every removal decision is yours, made by hand.** The Bouncer only reads and reports; "
          "it never unfollows, removes, blocks, mutes or reports anyone. \"Suspected\" means a pattern match, not proof."]
    return "\n".join(L) + "\n"


def write_report(snap_path, cfg, snap_dir="snapshots", rep_dir="reports"):
    with open(snap_path) as f:
        snap = json.load(f)
    prev = previous_snapshot(snap_path, snap_dir)
    md = build_report(snap, prev, cfg)
    os.makedirs(rep_dir, exist_ok=True)
    out = os.path.join(rep_dir, os.path.basename(snap_path).replace(".json", ".md"))
    with open(out, "w") as f:
        f.write(md)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    return out
