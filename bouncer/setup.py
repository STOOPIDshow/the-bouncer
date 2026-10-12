"""First-run setup wizard: python3 -m bouncer setup
Asks for handle, cap and cadence, writes config.yaml, checks the 4 credentials exist
(never prints them), then runs the cost estimate BEFORE any scan and refuses if over cap."""
import os, re, shutil, sys

from . import core
from .xclient import ENV_KEYS, XClient

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(HERE, "config.example.yaml")

CONSOLE_STEPS = """
Before you start (about 5 minutes at https://console.x.com):
  1. Create a Project (Production is fine), then create an app INSIDE it.
  2. User authentication settings -> App permissions: Read only.
  3. Keys and tokens: copy the API Key + API Key Secret.
     Then generate the Access Token + Access Token Secret (NOT the Bearer Token).
     GOTCHA: "Regenerate" replaces the API Key AND Secret together and can cancel
     older access tokens. If you regenerate, copy both again and generate the access
     token AFTER. The token page should say "Read only".
  4. Billing: load credits (or add a card), set a monthly spending limit, auto-recharge OFF.
"""

ENROLL_FIX = """
X said "client-not-enrolled" (HTTP 403). Your keys work, but the app has no API access yet:
  - Make sure the app sits inside a Project (create one and add the app, or create the app from it).
  - Make sure the account has pay-per-use credits loaded or a card on file.
Then run: python3 -m bouncer setup   (no new keys needed unless you regenerated)
"""

UNAUTH_FIX = """
X rejected the credentials (HTTP 401). Usually this means a key was regenerated after you copied it.
Copy the API Key + Secret again, regenerate the Access Token + Secret afterward, and re-export all four.
"""


def ask(prompt, default, valid=None, cast=str):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip() or str(default)
        try:
            val = cast(raw)
        except ValueError:
            print("  Not a valid value, try again."); continue
        if valid and not valid(val):
            print("  Not a valid value, try again."); continue
        return val


def write_config(path, handle, cap, cadence):
    with open(EXAMPLE) as f:
        text = f.read()
    text = re.sub(r"^handle:\s*\S+", f"handle: {handle}", text, flags=re.M)
    text = re.sub(r"^monthly_spend_cap_usd:\s*\S+", f"monthly_spend_cap_usd: {cap:.2f}", text, flags=re.M)
    text = re.sub(r"^scan_cadence:\s*\S+", f"scan_cadence: {cadence}", text, flags=re.M)
    with open(path, "w") as f:
        f.write(text)


def check_env():
    """Returns the list of missing env var NAMES. Never reads out values."""
    return [k for k in ENV_KEYS if not os.environ.get(k)]


def run(config_path="config.yaml", handle=None, cap=None, cadence=None, client=None, interactive=True):
    print("The Bouncer setup. Read-only: it never follows, unfollows, blocks, mutes, posts or DMs.")
    print(CONSOLE_STEPS)
    if interactive:
        handle = handle or ask("Your X handle (without @)", "", lambda v: re.fullmatch(r"@?\w{1,15}", v))
        cap = cap if cap is not None else ask("Monthly spending cap in USD", 10, lambda v: v > 0, float)
        cadence = cadence or ask("Scan cadence (weekly/monthly/quarterly)", "monthly",
                                 lambda v: v in core.CADENCE_SCANS_PER_MONTH)
    handle = (handle or "").lstrip("@")
    cadence = cadence or "monthly"
    if not re.fullmatch(r"\w{1,15}", handle) or cap is None or cadence not in core.CADENCE_SCANS_PER_MONTH:
        print("Need a valid handle, a cap and a cadence (weekly|monthly|quarterly)."); return 1
    write_config(config_path, handle, float(cap), cadence)
    print(f"\nWrote {config_path} (no secrets in it). Edit it later for protect list and thresholds.")

    if client is None:
        missing = check_env()
        if missing:
            print("\nMissing credentials: " + ", ".join(missing))
            print("Set them in your shell (don't put them in a file in this folder, never paste them in chat):")
            print("  export " + " ".join(f"{k}=..." for k in ENV_KEYS))
            print("Then run setup again.")
            return 1
        print("All 4 credentials found (values not shown).")
        client = XClient()

    cfg = core.load_config(config_path)
    print("\nRunning the cost estimate (1 user lookup, about $0.01)...")
    try:
        e = core.estimate(client, cfg)
    except RuntimeError as err:
        msg = str(err)
        if "client-not-enrolled" in msg or "client not enrolled" in msg.lower():
            print(ENROLL_FIX); return 3
        if " 401 " in msg:
            print(UNAUTH_FIX); return 3
        print("Estimate failed:", msg); return 3
    print(core.format_estimate(e))
    if not e["within_cap"]:
        print(f"\nREFUSED: projected ${e['monthly_usd']:.2f}/month is over your ${e['cap_usd']:.2f} cap.")
        print("Raise monthly_spend_cap_usd or pick a slower cadence, then run setup again. Nothing was scanned.")
        return 2
    print("\nYou're set. Run your first scan with: python3 -m bouncer scan")
    print("Also set the same spending limit in console.x.com so X enforces it too.")
    return 0
