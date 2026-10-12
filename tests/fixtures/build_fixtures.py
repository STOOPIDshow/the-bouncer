"""Generates tests/fixtures/*.json: mocked X API v2 responses for two weekly scans."""
import json, os
D = os.path.dirname(__file__)
EPOCH = 1288834974657
import datetime as dt
def sf(date):  # snowflake id for a date
    ms = int(dt.datetime.fromisoformat(date + "T12:00:00+00:00").timestamp() * 1000)
    return str((ms - EPOCH) << 22)
def user(i, name, fol=300, fing=200, tw=500, created="2015-01-01", bio="Building things.", avatar="https://pbs.twimg.com/profile_images/1/a.jpg", last="2026-10-01"):
    u = {"id": str(i), "username": name, "name": name, "created_at": created + "T00:00:00.000Z", "description": bio,
         "profile_image_url": avatar, "public_metrics": {"followers_count": fol, "following_count": fing, "tweet_count": tw, "listed_count": 0}}
    if last: u["most_recent_tweet_id"] = sf(last)
    return u
DEF = "https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png"
me = {"id": "999", "username": "example_user", "name": "Example User", "created_at": "2020-01-01T00:00:00.000Z",
      "public_metrics": {"followers_count": 7, "following_count": 4, "tweet_count": 120, "listed_count": 1}}
alice = user(1, "alice_dev"); bob = user(2, "bobmakes"); leaver = user(3, "leaving_larry")
bot1 = user(4, "user84736251", fol=3, fing=4800, tw=0, created="2026-10-01", bio="Crypto airdrop daily, DM me", avatar=DEF, last=None)
bot2 = user(5, "promo_queen", fol=10, fing=2500, tw=4, bio="NFT giveaway, link in bio")       # 3 signals
borderline = user(6, "sam19", fol=20, fing=50, tw=10)                                          # 1 signal
shield = user(7, "arg_runner", fol=5, fing=3000, tw=0, bio="Lost? #NightSignalARG", avatar=DEF)  # protected by hashtag
engager_bot = user(8, "loud4567890", fol=2, fing=1500, tw=900, avatar=DEF)                      # protected by mention
week1 = [alice, bob, leaver, borderline]
week2 = [alice, bob, bot1, bot2, borderline, shield, engager_bot]
following = [alice, user(20, "ghost_gus", last="2025-12-01"), user(21, "never_posted", tw=0, last=None),
             user(22, "fresh_fran", last="2026-10-10")]
def page(data, nt=None, includes=None):
    b = {"data": data, "meta": {"result_count": len(data)}}
    if nt: b["meta"]["next_token"] = nt
    if includes: b["includes"] = includes
    return b
mentions = [
  {"id": sf("2026-10-05"), "text": "@example_user lol", "author_id": "1", "created_at": "2026-10-05T10:00:00.000Z"},
  {"id": sf("2026-10-06"), "text": "@example_user yes", "author_id": "1", "created_at": "2026-10-06T10:00:00.000Z"},
  {"id": sf("2026-09-20"), "text": "@example_user hi", "author_id": "8", "created_at": "2026-09-20T10:00:00.000Z"},
  {"id": sf("2026-09-01"), "text": "@example_user great", "author_id": "30", "created_at": "2026-09-01T10:00:00.000Z"},
]
inc = {"users": [{"id": "1", "username": "alice_dev"}, {"id": "8", "username": "loud4567890"}, {"id": "30", "username": "outsider_olive"}]}
posts = [
  {"id": sf("2026-10-08"), "text": "New drop this week", "created_at": "2026-10-08T15:00:00.000Z", "public_metrics": {"like_count": 40, "reply_count": 5, "retweet_count": 3, "quote_count": 1}},
  {"id": sf("2026-08-20"), "text": "old post", "created_at": "2026-08-20T15:00:00.000Z", "public_metrics": {"like_count": 2, "reply_count": 0, "retweet_count": 0, "quote_count": 0}},
]
fx = {
 "me": {"data": me},
 "week1_followers": [page(week1[:2], "p2"), page(week1[2:])],
 "week2_followers": [page(week2[:4], "p2"), page(week2[4:])],
 "following": [page(following)],
 "mentions": [page(mentions[:2], "m2", inc), page(mentions[2:], None, inc)],
 "posts": [page(posts)],
}
for k, v in fx.items():
    json.dump(v, open(os.path.join(D, k + ".json"), "w"), indent=1)
if __name__ == "__main__": print("fixtures written")
