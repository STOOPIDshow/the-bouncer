import datetime as dt, json, os, pathlib, re, sys, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bouncer import core, xclient
from bouncer.xclient import XClient, ReadOnlyViolation, guard
FX = ROOT / "tests" / "fixtures"
def fx(n): return json.loads((FX / f"{n}.json").read_text())
CFG = core.load_config(ROOT / "config.example.yaml")
CFG["protect"] = {"handles": [], "hashtags": ["#NightSignalARG"]}

class Fake:
    """Mock transport: serves fixture pages, records every call, injects one 429."""
    def __init__(self, followers_key, rate_limit_once=True):
        self.calls, self.fk, self.rl = [], followers_key, rate_limit_once
    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if self.rl:
            self.rl = False
            return 429, {"x-rate-limit-reset": "0"}, {"title": "Too Many Requests"}
        if path.startswith("/2/users/by/username/"): return 200, {}, fx("me")
        kind = path.rsplit("/", 1)[1]
        pages = {"followers": fx(self.fk), "following": fx("following"), "mentions": fx("mentions"), "tweets": fx("posts")}[kind]
        tok = params.get("pagination_token")
        idx = 0 if not tok else [i for i, p in enumerate(pages) if i > 0 and pages[i - 1]["meta"].get("next_token") == tok][0]
        return 200, {}, pages[idx]

def run_scan(tmp, key, day):
    sleeps = []
    c = XClient(transport=Fake(key), sleep=sleeps.append)
    path, snap = core.scan(c, CFG, out_dir=tmp, now=dt.datetime(2026, 10, day, 12, tzinfo=dt.timezone.utc))
    return c, path, snap, sleeps

class Guard(unittest.TestCase):
    def test_non_get_refused(self):
        for m in ["POST", "DELETE", "PUT", "PATCH"]:
            with self.assertRaises(ReadOnlyViolation): guard(m, "/2/users/1/following")
        c = XClient(transport=lambda p, q: (200, {}, {}))
        with self.assertRaises(ReadOnlyViolation): c.get("/2/users/1/following", method="POST")
    def test_endpoint_allowlist(self):
        for p in ["/2/users/1/blocking", "/2/users/1/muting", "/2/tweets", "/2/users/1/likes", "/2/dm_events", "/2/users/1/following/2"]:
            with self.assertRaises(ReadOnlyViolation): guard("GET", p)
        for p in ["/2/users/1/followers", "/2/users/1/following", "/2/users/1/mentions", "/2/users/1/tweets", "/2/users/by/username/x"]:
            guard("GET", p)
    def test_source_has_no_write_calls(self):
        src = "\n".join(p.read_text() for p in (ROOT / "bouncer").glob("*.py"))
        for bad in ["POST", "DELETE", "PUT", "/blocking", "/muting", "/likes", "dm_conversations", "/retweets", "selenium", "playwright"]:
            if bad in ("POST", "DELETE", "PUT"):
                self.assertNotRegex(src, rf'method\s*=\s*"{bad}"')
            else:
                self.assertNotIn(bad, src)
    def test_missing_env_creds(self):
        for k in xclient.ENV_KEYS: os.environ.pop(k, None)
        with self.assertRaises(SystemExit): XClient()
    def test_oauth_signature_known_vector(self):
        # Twitter's documented OAuth 1.0a example vector
        creds = {"X_API_KEY": "xvz1evFS4wEEPTGEFPHBog", "X_API_SECRET": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                 "X_ACCESS_TOKEN": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "X_ACCESS_TOKEN_SECRET": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"}
        h = xclient.oauth1_header("POST", "https://api.twitter.com/1.1/statuses/update.json",
            {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"}, creds,
            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts=1318622958)
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', h)

class Estimate(unittest.TestCase):
    def test_cost_and_cap(self):
        c = XClient(transport=Fake("week1_followers", False))
        e = core.estimate(c, CFG)
        self.assertEqual(len(c.transport.calls), 1)
        self.assertAlmostEqual(e["per_scan_users_usd"], 0.011)
        self.assertTrue(e["within_cap"])
        big = {"data": {**fx("me")["data"], "public_metrics": {"followers_count": 200000, "following_count": 5000, "tweet_count": 10}}}
        class B(Fake):
            def __call__(s, p, q): s.calls.append((p, q)); return 200, {}, big
        c2 = XClient(transport=B("x", False))
        e2 = core.estimate(c2, CFG)
        self.assertAlmostEqual(e2["per_scan_users_usd"], 205.0)
        self.assertFalse(e2["within_cap"])
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            core.scan(c2, CFG, out_dir=t)
        self.assertTrue(all("/followers" not in p for p, _ in c2.transport.calls))

class ScanAndReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = self.tmp.name
    def tearDown(self): self.tmp.cleanup()
    def test_full_cycle(self):
        c1, p1, s1, sleeps = run_scan(self.t, "week1_followers", 5)
        self.assertEqual(sleeps, [1])  # 429 backoff
        self.assertEqual(len(s1["followers"]), 4)
        fcall = [q for p, q in c1.transport.calls if p.endswith("/followers")][0]
        self.assertEqual(fcall["max_results"], 1000)
        self.assertIn("most_recent_tweet_id", fcall["user.fields"])
        mcall = [q for p, q in c1.transport.calls if p.endswith("/mentions")][0]
        self.assertEqual(mcall["start_time"], "2026-07-07T12:00:00Z")
        r1 = core.build_report(s1, None, CFG)
        self.assertIn("First snapshot", r1)
        c2, p2, s2, _ = run_scan(self.t, "week2_followers", 12)
        self.assertTrue(p2.endswith("2026-10-12.json"))
        rp = core.write_report(p2, CFG, snap_dir=self.t, rep_dir=os.path.join(self.t, "r"))
        r = pathlib.Path(rp).read_text(); print("\n" + r)
        sec = lambda name: r.split(f"## {name}")[1].split("\n## ")[0]
        new = sec("New followers")
        self.assertIn("since last scan (2026-10-05, 7 days)", r)
        self.assertFalse([l for l in r.splitlines() if l.startswith("#") and "this week" in l])
        self.assertIn("4 new: 2 look real, 2 suspected bots", new)
        self.assertIn("@user84736251", new); self.assertIn("@promo_queen", new)
        self.assertIn("@leaving_larry", sec("Who left"))
        self.assertIn("New drop this week", sec("Posts that went out")); self.assertNotIn("old post", sec("Posts that went out"))
        top = sec("Top 10")
        self.assertRegex(top, r"1\. @alice_dev: 2 interactions"); self.assertIn("outsider_olive", top)
        bots = sec("Likely bots")
        self.assertIn("@user84736251 (7 signals)", bots)
        self.assertNotIn("@sam19", bots)
        self.assertNotIn("- @arg_runner", bots); self.assertIn("@arg_runner (bio contains #NightSignalARG)", bots)
        self.assertIn("@loud4567890 (replied/quoted/mentioned", bots)
        dead = sec("Dead follows")
        self.assertIn("@ghost_gus: last post 2025-12-01", dead); self.assertIn("@never_posted: has never posted", dead)
        self.assertNotIn("fresh_fran", dead); self.assertNotIn("@alice_dev", dead)
        self.assertNotRegex(r.lower(), r"\bconfirmed bot")
        self.assertIn("Every removal decision is yours, made by hand", r)
    def test_cadence(self):
        me = fx("me")["data"]
        base = None
        for cad, mult in [("monthly", 1), ("weekly", 52 / 12), ("quarterly", 1 / 3)]:
            e = core.estimate(None, {**CFG, "scan_cadence": cad}, me=me)
            self.assertEqual(e["cadence"], cad)
            base = base or e["per_scan_worst_usd"]
            self.assertAlmostEqual(e["monthly_usd"], round(base * mult, 2), places=2)
        self.assertEqual(CFG["scan_cadence"], "monthly"); self.assertGreater(CFG["monthly_spend_cap_usd"], 0)
        with self.assertRaises(SystemExit): core.estimate(None, {**CFG, "scan_cadence": "daily"}, me=me)
    def test_protect_handle(self):
        cfg = {**CFG, "protect": {"handles": ["@promo_queen"], "hashtags": []}}
        u = [x for x in fx("week2_followers")[0]["data"] if x["username"] == "promo_queen"][0]
        now = dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc)
        self.assertTrue(core.classify(u, CFG, now, {})["suspected_bot"])
        self.assertFalse(core.classify(u, cfg, now, {})["suspected_bot"])
    def test_snowflake(self):
        self.assertEqual(core.snowflake_time("1445078208190291968").date(), dt.date(2021, 10, 4))

class Setup(unittest.TestCase):
    def test_wizard_estimates_and_refuses_over_cap(self):
        from bouncer import setup
        with tempfile.TemporaryDirectory() as t:
            cp = os.path.join(t, "config.yaml")
            c = XClient(transport=Fake("week1_followers", False))
            self.assertEqual(setup.run(cp, "@someone", 5, "monthly", client=c, interactive=False), 0)
            cfg = core.load_config(cp)
            self.assertEqual((cfg["handle"], cfg["monthly_spend_cap_usd"], cfg["scan_cadence"]), ("someone", 5.0, "monthly"))
            self.assertEqual(len(c.transport.calls), 1)  # estimate only, no scan
            big = {"data": {**fx("me")["data"], "public_metrics": {"followers_count": 50000, "following_count": 2000, "tweet_count": 10}}}
            c2 = XClient(transport=lambda p, q: (200, {}, big))
            self.assertEqual(setup.run(cp, "someone", 5, "monthly", client=c2, interactive=False), 2)
            c3 = XClient(transport=lambda p, q: (403, {}, {"reason": "client-not-enrolled"}))
            self.assertEqual(setup.run(cp, "someone", 5, "monthly", client=c3, interactive=False), 3)
    def test_env_check_never_prints_values(self):
        from bouncer import setup
        import io, contextlib
        for k in xclient.ENV_KEYS: os.environ[k] = "SECRETVALUE123"
        os.environ.pop("X_ACCESS_TOKEN_SECRET")
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as t, contextlib.redirect_stdout(buf):
            self.assertEqual(setup.run(os.path.join(t, "c.yaml"), "someone", 5, "monthly", interactive=False), 1)
        self.assertNotIn("SECRETVALUE123", buf.getvalue()); self.assertIn("X_ACCESS_TOKEN_SECRET", buf.getvalue())
        for k in xclient.ENV_KEYS: os.environ.pop(k, None)
    def test_example_config_is_generic(self):
        txt = (ROOT / "config.example.yaml").read_text()
        self.assertIn("handle: your_handle_here", txt); self.assertIn("scan_cadence: monthly", txt)

if __name__ == "__main__": unittest.main(verbosity=2)
